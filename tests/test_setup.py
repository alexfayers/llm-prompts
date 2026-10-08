"""Tests for setup overlay/standalone inference across local and remote sources."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from conftest import FakeSubprocess

from llm_prompts import setup


@pytest.fixture(autouse=True)
def _clear_fetch_cache() -> None:
    """Reset the lru_cache on the real remote fetch before each test."""
    setup._fetch_remote_pyproject.cache_clear()


class TestReadPyproject:
    def test_local_valid(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\n', encoding="utf-8"
        )
        data = setup._read_pyproject({"name": "x", "source": str(tmp_path)})
        assert data == {"project": {"name": "x"}}

    def test_local_missing(self, tmp_path: Path) -> None:
        assert setup._read_pyproject({"name": "x", "source": str(tmp_path)}) is None

    def test_local_malformed(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("not = = valid [[[", encoding="utf-8")
        assert setup._read_pyproject({"name": "x", "source": str(tmp_path)}) is None

    def test_git_source_uses_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        canned = {"project": {"name": "remote"}}
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", lambda url: canned)
        data = setup._read_pyproject(
            {"name": "x", "source": "git+https://github.com/user/repo.git"}
        )
        assert data == canned

    def test_bare_pypi_never_fetches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = MagicMock()
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", mock)
        assert setup._read_pyproject({"name": "x", "source": "some-package"}) is None
        mock.assert_not_called()


class TestFetchRemotePyproject:
    def test_git_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("llm_prompts.setup.shutil.which", return_value=None):
            assert setup._fetch_remote_pyproject("https://x/repo.git") is None
        assert "git not available" in capsys.readouterr().err

    def test_clone_non_zero(
        self, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_subprocess.on("clone", returncode=1)
        with patch("llm_prompts.setup.shutil.which", return_value="/usr/bin/git"):
            assert setup._fetch_remote_pyproject("https://x/repo.git") is None
        assert "could not clone" in capsys.readouterr().err

    def test_clone_timeout(
        self, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_subprocess.on(
            "clone", side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30)
        )
        with patch("llm_prompts.setup.shutil.which", return_value="/usr/bin/git"):
            assert setup._fetch_remote_pyproject("https://x/repo.git") is None
        assert "timed out" in capsys.readouterr().err


class TestScriptNames:
    def test_declared_scripts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        data = {"project": {"scripts": {"foo": "pkg:main", "bar": "pkg:other"}}}
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", lambda url: data)
        assert setup._script_names(
            {"name": "x", "source": "git+https://github.com/user/repo.git"}
        ) == ["foo", "bar"]

    def test_no_scripts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            setup, "_fetch_remote_pyproject", lambda url: {"project": {}}
        )
        assert not setup._script_names(
            {"name": "x", "source": "git+https://github.com/user/repo.git"}
        )

    def test_bare_pypi(self) -> None:
        assert not setup._script_names({"name": "x", "source": "some-package"})


class TestValidatePaths:
    def test_bare_pypi_source_rejected(self) -> None:
        errors = setup._validate_paths(
            [{"name": "x", "source": "some-bare-package-name"}]
        )
        assert len(errors) == 1
        assert "some-bare-package-name" in errors[0]

    def test_git_url_source_ok(self) -> None:
        assert (
            setup._validate_paths(
                [{"name": "x", "source": "git+https://github.com/user/repo.git"}]
            )
            == []
        )

    def test_local_path_source_ok(self, tmp_path: Path) -> None:
        assert setup._validate_paths([{"name": "x", "source": str(tmp_path)}]) == []


class TestShippedConfig:
    def test_scripted_tools_are_installed_into_the_first_tools_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tools: list[dict[str, Any]] = tomllib.loads(setup._DEFAULT_CONFIG)["tools"]
        scripts = {
            "llm-prompts": {"project": {"scripts": {"llm-prompts": "x:main"}}},
            "cline-hooks": {"project": {"scripts": {"cline-hook": "x:main"}}},
            "mcp-memory": {"project": {"name": "mcp-memory"}},
        }
        monkeypatch.setattr(
            setup,
            "_fetch_remote_pyproject",
            lambda url: next(v for k, v in scripts.items() if k in url),
        )

        env = setup._build_commands(tools, set())

        assert env.name == "llm-prompts"
        assert env.members == ["cline-hooks", "mcp-memory"]
        assert env.scripts == ["llm-prompts", "cline-hook"]
        assert env.install_cmd[
            env.install_cmd.index("--with-executables-from") + 1
        ] == ("cline-hooks")


class TestUvCommands:
    def test_all_tools_install_into_the_first_tools_env_and_upgrade_reinstalls_only_changed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", lambda url: None)
        sources = {name: tmp_path / name for name in ("core", "cli", "lib")}
        for name, scripts in (("core", "core"), ("cli", "cli"), ("lib", "")):
            sources[name].mkdir()
            (sources[name] / "pyproject.toml").write_text(
                f'[project]\nname = "{name}"\n[project.scripts]\n'
                + (f'{scripts} = "{name}:main"\n' if scripts else ""),
                encoding="utf-8",
            )
        git_member = "git+https://example.com/git-member.git"
        tools: list[dict[str, Any]] = [
            {"name": "core", "source": str(sources["core"])},
            {"name": "cli", "source": str(sources["cli"])},
            {"name": "lib", "source": str(sources["lib"])},
            {"name": "git-member", "source": git_member},
        ]

        env = setup._build_commands(tools, {"cli"})

        assert env.install_cmd == [
            "uv",
            "tool",
            "install",
            str(sources["core"].resolve()),
            "--with",
            str(sources["cli"].resolve()),
            "--with",
            str(sources["lib"].resolve()),
            "--with",
            git_member,
            "--with-executables-from",
            "cli",
            "--no-sources-package",
            "core",
            "--no-sources-package",
            "cli",
            "--no-sources-package",
            "lib",
            "--reinstall",
            "--force",
        ]
        assert env.upgrade_cmd == [
            "uv",
            "tool",
            "upgrade",
            "core",
            "--reinstall-package",
            "cli",
        ]

    def test_setup_without_uv_exits_with_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("llm_prompts.setup.shutil.which", lambda name: None)

        with pytest.raises(SystemExit):
            setup._require_uv()

        assert "setup needs uv" in capsys.readouterr().err


class TestEnvDrift:
    @staticmethod
    def _receipt(requirements: list[str], entrypoints: list[str]) -> str:
        def table(names: list[str]) -> str:
            return ", ".join(f'{{ name = "{name}" }}' for name in names)

        return (
            f"[tool]\nrequirements = [{table(requirements)}]\n"
            f"entrypoints = [{table(entrypoints)}]\n"
        )

    @pytest.mark.parametrize(
        ("requirements", "entrypoints", "drifted"),
        [
            (["core", "cli"], ["core", "cli"], False),
            (["core"], ["core", "cli"], True),
            (["core", "cli"], ["core"], True),
            (None, None, True),
        ],
        ids=["complete", "missing-member", "missing-script", "no-receipt"],
    )
    def test_env_drifts_when_receipt_lacks_a_member_or_script(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        requirements: list[str] | None,
        entrypoints: list[str] | None,
        drifted: bool,
    ) -> None:
        monkeypatch.setattr(setup, "_uv_tools_dir", lambda: tmp_path)
        if requirements is not None and entrypoints is not None:
            (tmp_path / "core").mkdir()
            (tmp_path / "core" / "uv-receipt.toml").write_text(
                self._receipt(requirements, entrypoints), encoding="utf-8"
            )
        env = setup.SharedEnv("core", [], [], ["cli"], ["core", "cli"])

        assert setup._has_drifted(env) is drifted


class TestChangedLocalTools:
    @pytest.fixture
    def checkouts(
        self,
        tmp_path: Path,
        fake_subprocess: FakeSubprocess,
        monkeypatch: pytest.MonkeyPatch,
    ) -> list[dict[str, Any]]:
        monkeypatch.setattr(
            setup, "_checkout_stamp_path", lambda: tmp_path / "checkout-stamp"
        )
        tools: list[dict[str, Any]] = [
            {"name": "core", "source": str(tmp_path / "core")},
            {"name": "overlay", "source": str(tmp_path / "overlay")},
            {"name": "remote", "source": "git+https://example.com/remote.git"},
        ]
        for tool in tools[:2]:
            repo = (tmp_path / tool["name"]).resolve()
            for verb in ("ls-files", "status", "diff"):
                fake_subprocess.on(verb, repo=repo, stdout=f"{tool['name']} {verb}")
        return tools

    def test_only_checkouts_that_differ_from_the_stamp_are_changed(
        self,
        tmp_path: Path,
        checkouts: list[dict[str, Any]],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        setup.write_checkout_stamp(checkouts)
        assert setup.detect_changed_local_tools(checkouts) == set()

        fake_subprocess.on(
            "status", repo=(tmp_path / "overlay").resolve(), stdout=" M file.py"
        )
        assert setup.detect_changed_local_tools(checkouts) == {"overlay"}

    def test_checkout_state_ignores_prompts(
        self,
        checkouts: list[dict[str, Any]],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        setup.detect_changed_local_tools(checkouts)

        git_calls = [argv for argv, _ in fake_subprocess.calls if argv[0] == "git"]
        assert git_calls
        assert all(argv[-1] == setup._NOT_PROMPTS for argv in git_calls)

    def test_every_local_tool_is_changed_without_a_stamp(
        self, checkouts: list[dict[str, Any]]
    ) -> None:
        assert setup.detect_changed_local_tools(checkouts) == {"core", "overlay"}

    def test_checkout_with_failing_git_is_changed(
        self,
        tmp_path: Path,
        checkouts: list[dict[str, Any]],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        setup.write_checkout_stamp(checkouts)
        fake_subprocess.on(
            "ls-files", repo=(tmp_path / "core").resolve(), returncode=128
        )
        assert setup.detect_changed_local_tools(checkouts) == {"core"}


class TestRunSetup:
    @pytest.fixture
    def tools_dir(
        self,
        tmp_path: Path,
        fake_subprocess: FakeSubprocess,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Path:
        tools: list[dict[str, Any]] = []
        for name in ("core", "cli"):
            source = tmp_path / name
            source.mkdir()
            (source / "pyproject.toml").write_text(
                f'[project]\nname = "{name}"\n[project.scripts]\n{name} = "{name}:main"\n'
            )
            tools.append({"name": name, "source": str(source)})
        tools_dir = tmp_path / "uv-tools"
        self.write_receipt(tools_dir, ["core", "cli"])
        monkeypatch.setattr(setup, "_load_config", lambda: tools)
        monkeypatch.setattr(setup, "_require_uv", lambda: None)
        monkeypatch.setattr(setup, "_uv_tools_dir", lambda: tools_dir)
        monkeypatch.setattr(
            setup, "_pyproject_stamp_path", lambda: tmp_path / "pyproject-stamp"
        )
        return tools_dir

    @staticmethod
    def write_receipt(tools_dir: Path, entrypoints: list[str]) -> None:
        names = ", ".join(f'{{ name = "{name}" }}' for name in entrypoints)
        (tools_dir / "core").mkdir(parents=True, exist_ok=True)
        (tools_dir / "core" / "uv-receipt.toml").write_text(
            f'[tool]\nrequirements = [{{ name = "core" }}, {{ name = "cli" }}]\n'
            f"entrypoints = [{names}]\n"
        )

    def test_second_run_without_checkout_changes_reinstalls_nothing(
        self, tools_dir: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        setup.run_setup()
        setup.run_setup()

        first, second = fake_subprocess.matching("uv", "tool", "upgrade")
        assert "--reinstall-package" in first
        assert "--reinstall-package" not in second
        assert not fake_subprocess.matching("uv", "tool", "install")

    def test_named_tool_forces_a_full_reinstall_of_the_shared_env(
        self, tools_dir: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        setup.run_setup("cli")

        assert not fake_subprocess.matching("uv", "tool", "upgrade")
        assert len(fake_subprocess.matching("uv", "tool", "install")) == 1
        assert not fake_subprocess.matching("uv", "tool", "uninstall")

    def test_full_install_removes_members_old_tool_envs_then_installs_again(
        self,
        tools_dir: Path,
        fake_subprocess: FakeSubprocess,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tools_dir / "cli").mkdir()

        setup.run_setup("core")

        install, uninstall, reinstall = [
            c for c in fake_subprocess.commands if c[0] == "uv"
        ]
        assert install[:3] == ["uv", "tool", "install"]
        assert uninstall == ["uv", "tool", "uninstall", "cli"]
        assert reinstall == install
        assert "[cli] removed old tool env" in capsys.readouterr().out

    def test_upgrade_run_retries_removing_a_leftover_member_env(
        self, tools_dir: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        (tools_dir / "cli").mkdir()

        setup.run_setup()

        assert [c[:3] for c in fake_subprocess.commands if c[0] == "uv"] == [
            ["uv", "tool", "upgrade"],
            ["uv", "tool", "uninstall"],
            ["uv", "tool", "install"],
        ]

    def test_failed_install_keeps_members_old_tool_envs(
        self, tools_dir: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        (tools_dir / "cli").mkdir()
        fake_subprocess.on("uv", "tool", "install", returncode=1)

        with pytest.raises(SystemExit):
            setup.run_setup("core")

        assert not fake_subprocess.matching("uv", "tool", "uninstall")

    def test_unknown_tool_name_exits(
        self,
        tools_dir: Path,
        fake_subprocess: FakeSubprocess,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit):
            setup.run_setup("missing")

        assert "No tool named 'missing'" in capsys.readouterr().err
        assert not fake_subprocess.commands

    def test_upgrade_that_drops_scripts_falls_back_to_a_full_install(
        self, tools_dir: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        self.write_receipt(tools_dir, ["core"])

        setup.run_setup()

        assert len(fake_subprocess.matching("uv", "tool", "install")) == 1


class TestRunParallelOrdered:
    def test_empty_input_returns_empty_list(self) -> None:
        assert setup._run_parallel_ordered([]) == []

    def test_preserves_submission_order(self) -> None:
        calls = [lambda: ["a"], lambda: ["b"], lambda: ["c"]]
        assert setup._run_parallel_ordered(calls) == [["a"], ["b"], ["c"]]


class TestRemoteHead:
    def test_returns_remote_sha(self, fake_subprocess: FakeSubprocess) -> None:
        fake_subprocess.on("ls-remote", stdout="deadbeef\tHEAD\n")
        assert setup._remote_head("https://x/repo.git", None) == "deadbeef"

    def test_returns_none_on_failure(self, fake_subprocess: FakeSubprocess) -> None:
        fake_subprocess.on("ls-remote", returncode=128)
        assert setup._remote_head("https://x/repo.git", None) is None

    def test_returns_none_on_empty_output(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("ls-remote", stdout="")
        assert setup._remote_head("https://x/repo.git", "main") is None


class TestCommitSubjectsBetween:
    def test_lists_subjects_between_shas(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        fake_subprocess.on(
            "log",
            "--pretty=format:%s%n%b%x1e",
            repo=repo,
            stdout=fake_subprocess.log_lines("third", "second"),
        )
        assert setup._commit_subjects_between(repo, "base", "tip") == [
            "third",
            "second",
        ]

    def test_keeps_only_listed_commit_body_lines_with_their_subject(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        fake_subprocess.on(
            "log",
            "--pretty=format:%s%n%b%x1e",
            repo=repo,
            stdout=fake_subprocess.log_lines(
                "feat: batch\n\n* feat: a\n\n* feat: b\n\nmore text\n", "fix: c"
            ),
        )
        assert setup._commit_subjects_between(repo, "base", "tip") == [
            "feat: batch\n* feat: a\n* feat: b",
            "fix: c",
        ]

    def test_drops_merge_commits_listed_in_a_squash_body(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        fake_subprocess.on(
            "log",
            "--pretty=format:%s%n%b%x1e",
            repo=repo,
            stdout=fake_subprocess.log_lines(
                "feat: batch\n\n* feat: a\n\n* Merge branch 'main' into feat/a\n"
            ),
        )
        assert setup._commit_subjects_between(repo, "base", "tip") == [
            "feat: batch\n* feat: a"
        ]

    def test_squash_with_listed_commits_is_headed_by_its_pr_number(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        fake_subprocess.on(
            "log",
            "--pretty=format:%s%n%b%x1e",
            repo=repo,
            stdout=fake_subprocess.log_lines(
                "feat: add foo (+1 more) (#101)\n\n* feat: add foo\n\n* feat: add bar\n"
            ),
        )
        assert setup._commit_subjects_between(repo, "base", "tip") == [
            "PR #101\n* feat: add foo\n* feat: add bar"
        ]

    def test_more_suffix_is_stripped_from_a_subject(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        fake_subprocess.on(
            "log",
            "--pretty=format:%s%n%b%x1e",
            repo=repo,
            stdout=fake_subprocess.log_lines("feat: add foo (+2 more) (#101)"),
        )
        assert setup._commit_subjects_between(repo, "base", "tip") == [
            "feat: add foo (#101)"
        ]

    def test_skips_merge_commits(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        fake_subprocess.on("log", "--pretty=format:%s%n%b%x1e", repo=repo)
        setup._commit_subjects_between(repo, "base", "tip")
        assert "--no-merges" in fake_subprocess.matching("log")[0]

    def test_returns_none_on_failure(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        fake_subprocess.on("log", "--pretty=format:%s%n%b%x1e", repo=repo, returncode=1)
        assert setup._commit_subjects_between(repo, "nope1", "nope2") is None


class TestFormatUpdateMessage:
    def test_lists_subjects(self) -> None:
        result = setup._format_update_message("core", ["Add feature X", "Fix bug Y"])
        assert len(result) == 1
        assert result[0] == ("[core] update available:\n- Add feature X\n- Fix bug Y")

    def test_caps_list_and_reports_remainder(self) -> None:
        subjects = [f"commit {i}" for i in range(25)]
        result = setup._format_update_message("core", subjects, cap=20)
        body = result[0]
        assert "- commit 19" in body
        assert "- commit 20" not in body
        assert "... and 5 more" in body

    def test_indents_body_lines_under_their_subject(self) -> None:
        result = setup._format_update_message(
            "core", ["feat: batch\n* feat: a\n* feat: b", "fix: c"]
        )
        assert result[0] == (
            "[core] update available:\n"
            "- feat: batch\n"
            "  * feat: a\n"
            "  * feat: b\n"
            "- fix: c"
        )

    def test_cap_counts_commits_not_body_lines(self) -> None:
        messages = [f"commit {i}\nbody {i}" for i in range(21)]
        body = setup._format_update_message("core", messages, cap=20)[0]
        assert "  body 19" in body
        assert "commit 20" not in body
        assert "... and 1 more" in body

    def test_falls_back_to_sha_pair_when_subjects_missing(self) -> None:
        assert setup._format_update_message(
            "core", None, local="abc123aa", remote="def456bb"
        ) == ["[core] update available (abc123aa -> def456bb)"]

    def test_falls_back_to_bare_message_without_shas(self) -> None:
        assert setup._format_update_message("core", []) == ["[core] update available"]
