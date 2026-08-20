"""Tests for CLI update check functionality."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import patch, MagicMock

import pytest


from llm_prompts.cli import (
    _check_for_updates,
    _collect_sources,
    _collect_update_messages,
    _get_installed_commit,
    _local_source_messages,
    _pull_local_sources,
    _remote_source_messages,
    main,
)
from llm_prompts.setup import (
    _extract_git_url,
    detect_stale_local_tools,
    run_setup,
    write_pyproject_stamp,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


class TestExtractGitUrl:
    def test_git_plus_https(self) -> None:
        assert (
            _extract_git_url("git+https://github.com/user/repo.git")
            == "https://github.com/user/repo.git"
        )

    def test_git_plus_ssh(self) -> None:
        assert (
            _extract_git_url("git+ssh://git@github.com/user/repo.git")
            == "ssh://git@github.com/user/repo.git"
        )

    def test_plain_https(self) -> None:
        assert (
            _extract_git_url("https://github.com/user/repo.git")
            == "https://github.com/user/repo.git"
        )

    def test_local_path(self) -> None:
        assert _extract_git_url("~/git/llm-prompts") is None

    def test_relative_path(self) -> None:
        assert _extract_git_url("./local-package") is None

    def test_pypi_name(self) -> None:
        assert _extract_git_url("some-package") is None


class TestGetInstalledCommit:
    def test_finds_commit_from_vcs_info(self, tmp_path: Path) -> None:
        dist_info = (
            tmp_path
            / "llm-prompts"
            / "lib"
            / "python3.14"
            / "site-packages"
            / "my_tool-0.1.0.dist-info"
        )
        dist_info.mkdir(parents=True)
        direct_url = dist_info / "direct_url.json"
        direct_url.write_text(
            json.dumps(
                {
                    "url": "https://github.com/user/repo.git",
                    "vcs_info": {
                        "vcs": "git",
                        "commit_id": "abc123def456",
                    },
                }
            )
        )

        with patch("llm_prompts.cli.Path.home", return_value=tmp_path / "fake_home"):
            uv_tools = tmp_path / "fake_home" / ".local" / "share" / "uv" / "tools"
            uv_tools.mkdir(parents=True)
            (uv_tools / "my-tool").symlink_to(tmp_path / "llm-prompts")

            result = _get_installed_commit("my-tool")
            assert result == "abc123def456"

    def test_returns_none_for_editable_install(self, tmp_path: Path) -> None:
        dist_info = (
            tmp_path
            / "my-tool"
            / "lib"
            / "python3.14"
            / "site-packages"
            / "my_tool-0.1.0.dist-info"
        )
        dist_info.mkdir(parents=True)
        direct_url = dist_info / "direct_url.json"
        direct_url.write_text(
            json.dumps(
                {
                    "url": "file:///Users/someone/git/my-tool",
                    "dir_info": {"editable": True},
                }
            )
        )

        with patch("llm_prompts.cli.Path.home", return_value=tmp_path / "fake_home"):
            uv_tools = tmp_path / "fake_home" / ".local" / "share" / "uv" / "tools"
            uv_tools.mkdir(parents=True)
            (uv_tools / "my-tool").symlink_to(tmp_path / "my-tool")

            result = _get_installed_commit("my-tool")
            assert result is None

    def test_returns_none_when_not_installed(self, tmp_path: Path) -> None:
        with patch("llm_prompts.cli.Path.home", return_value=tmp_path / "fake_home"):
            uv_tools = tmp_path / "fake_home" / ".local" / "share" / "uv" / "tools"
            uv_tools.mkdir(parents=True)

            result = _get_installed_commit("nonexistent")
            assert result is None


class TestRemoteSourceMessages:
    def test_not_a_git_url(self) -> None:
        assert _remote_source_messages("pkg", "some-pypi-package") == []

    def test_not_installed(self) -> None:
        with patch("llm_prompts.cli._get_installed_commit", return_value=None):
            result = _remote_source_messages(
                "pkg", "git+https://github.com/user/repo.git"
            )
            assert result == ["[pkg] not installed (run `llm-prompts setup` first)"]

    def test_up_to_date(self) -> None:
        with (
            patch("llm_prompts.cli._get_installed_commit", return_value="abc123"),
            patch("llm_prompts.cli._remote_head", return_value="abc123"),
        ):
            result = _remote_source_messages(
                "pkg", "git+https://github.com/user/repo.git"
            )
            assert result == []

    def test_update_available_lists_commit_subjects(self) -> None:
        with (
            patch("llm_prompts.cli._get_installed_commit", return_value="abc123aa"),
            patch("llm_prompts.cli._remote_head", return_value="def456bb"),
            patch(
                "llm_prompts.cli._remote_commit_subjects",
                return_value=["Add X", "Fix Y"],
            ),
        ):
            result = _remote_source_messages(
                "pkg", "git+https://github.com/user/repo.git"
            )
            assert result == [
                "[pkg] update available:\n"
                "- Add X\n"
                "- Fix Y\n"
                "Summarize these changes for the user in plain language, and flag "
                "anything that looks like a breaking change."
            ]

    def test_update_available_falls_back_to_shas_when_clone_fails(self) -> None:
        with (
            patch("llm_prompts.cli._get_installed_commit", return_value="abc123aa"),
            patch("llm_prompts.cli._remote_head", return_value="def456bb"),
            patch("llm_prompts.cli._remote_commit_subjects", return_value=None),
        ):
            result = _remote_source_messages(
                "pkg", "git+https://github.com/user/repo.git"
            )
            assert result == ["[pkg] update available (abc123aa -> def456bb)"]

    def test_ls_remote_fails(self) -> None:
        with (
            patch("llm_prompts.cli._get_installed_commit", return_value="abc123"),
            patch("llm_prompts.cli._remote_head", return_value=None),
        ):
            result = _remote_source_messages(
                "pkg", "git+https://github.com/user/repo.git"
            )
            assert result == []


class TestLocalSourceMessages:
    def test_has_updates_lists_commit_subjects(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),
                MagicMock(returncode=0, stdout="3\n"),
                MagicMock(returncode=0, stdout="Add A\nFix B\nTweak C\n"),
            ]
            result = _local_source_messages("core", str(tmp_path))
            assert result == [
                "[core] update available:\n"
                "- Add A\n"
                "- Fix B\n"
                "- Tweak C\n"
                "Summarize these changes for the user in plain language, and flag "
                "anything that looks like a breaking change."
            ]

    def test_up_to_date(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),
                MagicMock(returncode=0, stdout="0\n"),
            ]
            result = _local_source_messages("core", str(tmp_path))
            assert result == []

    def test_no_git_dir(self, tmp_path: Path) -> None:
        assert _local_source_messages("core", str(tmp_path)) == []

    def test_rev_list_fails(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),
                MagicMock(returncode=128, stdout=""),
            ]
            result = _local_source_messages("core", str(tmp_path))
            assert result == []

    def test_log_failure_falls_back_to_bare_message(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),
                MagicMock(returncode=0, stdout="2\n"),
                MagicMock(returncode=128, stdout=""),
            ]
            result = _local_source_messages("core", str(tmp_path))
            assert result == ["[core] update available"]


class TestPullLocalSources:
    def _setup_clone(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a bare upstream and a local clone tracking it, with one commit."""
        upstream = tmp_path / "upstream.git"
        upstream.mkdir()
        _git(upstream, "init", "-q", "--bare")
        clone = tmp_path / "clone"
        _init_repo(clone)
        _commit(clone, "a.txt", "x\n", "init")
        _git(clone, "remote", "add", "origin", str(upstream))
        _git(clone, "push", "-q", "-u", "origin", "HEAD")
        return upstream, clone

    def test_diverged_repo_is_rebased_onto_upstream(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        upstream, clone = self._setup_clone(tmp_path)

        other_clone = tmp_path / "other-clone"
        _git(tmp_path, "clone", "-q", str(upstream), str(other_clone))
        _commit(other_clone, "b.txt", "y\n", "upstream change")
        _git(other_clone, "push", "-q")

        _commit(clone, "c.txt", "z\n", "local change")

        config = [{"name": "core", "source": str(clone)}]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                _pull_local_sources()

        log = _git(clone, "log", "--oneline", "-3").stdout
        assert "local change" in log
        assert "upstream change" in log
        assert (
            "[core] rebased local commits onto 1 new commit(s)"
            in capsys.readouterr().out
        )

    def test_fast_forwardable_repo_is_pulled_without_rebase(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        upstream, clone = self._setup_clone(tmp_path)

        other_clone = tmp_path / "other-clone"
        _git(tmp_path, "clone", "-q", str(upstream), str(other_clone))
        _commit(other_clone, "b.txt", "y\n", "upstream change")
        _git(other_clone, "push", "-q")

        config = [{"name": "core", "source": str(clone)}]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                _pull_local_sources()

        log = _git(clone, "log", "--oneline", "-2").stdout
        assert "upstream change" in log
        assert "[core] pulled 1 new commit(s)" in capsys.readouterr().out

    def test_conflicting_rebase_is_aborted_and_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        upstream, clone = self._setup_clone(tmp_path)

        other_clone = tmp_path / "other-clone"
        _git(tmp_path, "clone", "-q", str(upstream), str(other_clone))
        _commit(other_clone, "a.txt", "upstream-version\n", "upstream change")
        _git(other_clone, "push", "-q")

        _commit(clone, "a.txt", "local-version\n", "local change")

        config = [{"name": "core", "source": str(clone)}]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                _pull_local_sources()

        status = _git(clone, "status", "--porcelain=v1").stdout
        assert status == ""
        rebase_dirs = list((clone / ".git").glob("rebase-*"))
        assert rebase_dirs == []
        assert "[core] 1 new commit(s) available but rebase failed" in (
            capsys.readouterr().out
        )

    def _setup_ff_clone(self, tmp_path: Path, name: str) -> Path:
        """Create a clone that is one commit behind its upstream (fast-forwardable)."""
        upstream = tmp_path / f"{name}-upstream.git"
        upstream.mkdir()
        _git(upstream, "init", "-q", "--bare")
        clone = tmp_path / f"{name}-clone"
        _init_repo(clone)
        _commit(clone, "a.txt", "x\n", "init")
        _git(clone, "remote", "add", "origin", str(upstream))
        _git(clone, "push", "-q", "-u", "origin", "HEAD")

        other = tmp_path / f"{name}-other"
        _git(tmp_path, "clone", "-q", str(upstream), str(other))
        _commit(other, "b.txt", "y\n", "upstream change")
        _git(other, "push", "-q")
        return clone

    def test_output_lines_preserve_config_order(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        first = self._setup_ff_clone(tmp_path, "first")
        second = self._setup_ff_clone(tmp_path, "second")
        third = self._setup_ff_clone(tmp_path, "third")

        config = [
            {"name": "first", "source": str(first)},
            {"name": "second", "source": str(second)},
            {"name": "third", "source": str(third)},
        ]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                _pull_local_sources()

        assert capsys.readouterr().out.splitlines() == [
            "[first] pulled 1 new commit(s)",
            "[second] pulled 1 new commit(s)",
            "[third] pulled 1 new commit(s)",
        ]

    def test_rebase_failure_lines_stay_adjacent_and_ordered(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        conflict_upstream, conflict = self._setup_clone(tmp_path)
        other = tmp_path / "conflict-other"
        _git(tmp_path, "clone", "-q", str(conflict_upstream), str(other))
        _commit(other, "a.txt", "upstream-version\n", "upstream change")
        _git(other, "push", "-q")
        _commit(conflict, "a.txt", "local-version\n", "local change")

        ff = self._setup_ff_clone(tmp_path, "ff")

        config = [
            {"name": "conflict", "source": str(conflict)},
            {"name": "ff", "source": str(ff)},
        ]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                _pull_local_sources()

        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "[conflict] 1 new commit(s) available but rebase failed"
        assert lines[1].startswith("  ")
        assert lines[-1] == "[ff] pulled 1 new commit(s)"
        assert "[ff]" not in "\n".join(lines[:-1])


class TestCollectUpdateMessages:
    def test_no_config(self) -> None:
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = False
            assert _collect_update_messages() == []

    def test_mixed_sources(self) -> None:
        config = [
            {"name": "core", "source": "~/git/llm-prompts"},
            {"name": "remote-pkg", "source": "git+https://github.com/user/repo.git"},
        ]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with (
                patch("llm_prompts.setup._load_config", return_value=config),
                patch("llm_prompts.plugins._load_plugins", return_value=[]),
                patch(
                    "llm_prompts.cli._local_source_messages",
                    return_value=["[core] 2 new commit(s) available"],
                ) as mock_local,
                patch(
                    "llm_prompts.cli._remote_source_messages",
                    return_value=["[remote-pkg] update available (aa -> bb)"],
                ) as mock_remote,
            ):
                result = _collect_update_messages()

        assert result == [
            "[core] 2 new commit(s) available",
            "[remote-pkg] update available (aa -> bb)",
        ]
        mock_local.assert_called_once_with("core", "~/git/llm-prompts")
        mock_remote.assert_called_once_with(
            "remote-pkg", "git+https://github.com/user/repo.git"
        )

    def test_plugin_messages_appended_after_tools(self) -> None:
        config = [{"name": "core", "source": "~/git/llm-prompts"}]
        plugin = {"name": "p", "source": "https://github.com/u/r.git"}
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with (
                patch("llm_prompts.setup._load_config", return_value=config),
                patch(
                    "llm_prompts.cli._local_source_messages",
                    return_value=["[core] 1 new commit(s) available"],
                ),
                patch("llm_prompts.plugins._load_plugins", return_value=[plugin]),
                patch(
                    "llm_prompts.plugins.plugin_source_messages",
                    return_value=["[p] update available (aa -> bb)"],
                ) as mock_plugin,
            ):
                result = _collect_update_messages()

        assert result == [
            "[core] 1 new commit(s) available",
            "[p] update available (aa -> bb)",
        ]
        mock_plugin.assert_called_once_with(plugin)


class TestUpdateCommandPullsPlugins:
    def test_update_invokes_pull_plugin_sources(self) -> None:
        with (
            patch("sys.argv", ["llm-prompts", "update"]),
            patch(
                "llm_prompts.manifest.read_manifest",
                return_value={"kiro": {"files": []}},
            ),
            patch("llm_prompts.cli._pull_local_sources"),
            patch("llm_prompts.setup.has_remote_sources", return_value=False),
            patch("llm_prompts.setup.detect_stale_local_tools", return_value=set()),
            patch("llm_prompts.setup.run_setup") as mock_setup,
            patch("llm_prompts.install.main"),
            patch("llm_prompts.cli._restart_memory_service"),
            patch("llm_prompts.plugins.pull_plugin_sources") as mock_pull,
        ):
            main()

        mock_pull.assert_called_once_with()
        mock_setup.assert_not_called()

    def test_update_runs_setup_with_stale_tools(self) -> None:
        with (
            patch("sys.argv", ["llm-prompts", "update"]),
            patch(
                "llm_prompts.manifest.read_manifest",
                return_value={"kiro": {"files": []}},
            ),
            patch("llm_prompts.cli._pull_local_sources"),
            patch("llm_prompts.setup.CONFIG_PATH") as mock_config,
            patch("llm_prompts.setup.has_remote_sources", return_value=False),
            patch(
                "llm_prompts.setup.detect_stale_local_tools",
                return_value={"cline-hooks"},
            ),
            patch("llm_prompts.setup.run_setup") as mock_setup,
            patch("llm_prompts.install.main"),
            patch("llm_prompts.cli._restart_memory_service"),
            patch("llm_prompts.plugins.pull_plugin_sources"),
        ):
            mock_config.exists.return_value = True
            main()

        mock_setup.assert_called_once_with(force_reinstall={"cline-hooks"})

    def test_update_forces_stale_local_tool_even_with_remote_sources(self) -> None:
        with (
            patch("sys.argv", ["llm-prompts", "update"]),
            patch(
                "llm_prompts.manifest.read_manifest",
                return_value={"kiro": {"files": []}},
            ),
            patch("llm_prompts.cli._pull_local_sources"),
            patch("llm_prompts.setup.CONFIG_PATH") as mock_config,
            patch("llm_prompts.setup.has_remote_sources", return_value=True),
            patch(
                "llm_prompts.setup.detect_stale_local_tools",
                return_value={"cline-hooks"},
            ),
            patch("llm_prompts.setup.run_setup") as mock_setup,
            patch("llm_prompts.install.main"),
            patch("llm_prompts.cli._restart_memory_service"),
            patch("llm_prompts.plugins.pull_plugin_sources"),
        ):
            mock_config.exists.return_value = True
            main()

        mock_setup.assert_called_once_with(force_reinstall={"cline-hooks"})


class TestCollectSourcesOverlayPrecedence:
    def test_overlay_skill_wins_name_collision(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base_skill = base / "shared" / "skills" / "collide"
        base_skill.mkdir(parents=True)
        (base_skill / "SKILL.md").write_text("BASE\n")

        overlay = tmp_path / "overlay"
        overlay_skill = overlay / "shared" / "skills" / "collide"
        overlay_skill.mkdir(parents=True)
        (overlay_skill / "SKILL.md").write_text("OVERLAY\n")

        with patch("llm_prompts.cli._get_root_dir", return_value=base):
            with patch(
                "llm_prompts.install._discover_overlay_paths",
                return_value=[overlay],
            ):
                sources = _collect_sources("claude-code")

        assert sources["skills/collide"].read_text() == "OVERLAY\n"

    def test_overlay_agent_wins_name_collision(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base_agents = base / "claude-code" / "agents"
        base_agents.mkdir(parents=True)
        (base_agents / "collide.md").write_text("BASE\n")

        overlay = tmp_path / "overlay"
        overlay_agents = overlay / "claude-code" / "agents"
        overlay_agents.mkdir(parents=True)
        (overlay_agents / "collide.md").write_text("OVERLAY\n")

        with patch("llm_prompts.cli._get_root_dir", return_value=base):
            with patch(
                "llm_prompts.install._discover_overlay_paths",
                return_value=[overlay],
            ):
                sources = _collect_sources("claude-code")

        assert sources["agents/collide.md"].read_text() == "OVERLAY\n"


class TestDetectStaleLocalTools:
    def _write_tool(self, tmp_path: Path, name: str, content: str) -> dict[str, str]:
        repo = tmp_path / name
        repo.mkdir()
        (repo / "pyproject.toml").write_text(content)
        return {"name": name, "source": str(repo)}

    def test_no_config_returns_empty(self, tmp_path: Path) -> None:
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = False
            assert detect_stale_local_tools() == set()

    def test_no_stamp_file_returns_empty(self, tmp_path: Path) -> None:
        tool = self._write_tool(tmp_path, "core", "[project]\nname='core'\n")
        with (
            patch("llm_prompts.setup.CONFIG_PATH") as mock_config,
            patch("llm_prompts.setup._load_config", return_value=[tool]),
            patch(
                "llm_prompts.setup._pyproject_stamp_path",
                return_value=tmp_path / "stamp.json",
            ),
        ):
            mock_config.exists.return_value = True
            assert detect_stale_local_tools() == set()

    def test_matching_hash_is_not_stale(self, tmp_path: Path) -> None:
        tool = self._write_tool(tmp_path, "core", "[project]\nname='core'\n")
        stamp = tmp_path / "stamp.json"
        with (
            patch("llm_prompts.setup.CONFIG_PATH") as mock_config,
            patch("llm_prompts.setup._load_config", return_value=[tool]),
            patch("llm_prompts.setup._pyproject_stamp_path", return_value=stamp),
        ):
            mock_config.exists.return_value = True
            write_pyproject_stamp()
            assert detect_stale_local_tools() == set()

    def test_mismatched_hash_is_stale(self, tmp_path: Path) -> None:
        tool = self._write_tool(tmp_path, "core", "[project]\nname='core'\n")
        stamp = tmp_path / "stamp.json"
        with (
            patch("llm_prompts.setup.CONFIG_PATH") as mock_config,
            patch("llm_prompts.setup._load_config", return_value=[tool]),
            patch("llm_prompts.setup._pyproject_stamp_path", return_value=stamp),
        ):
            mock_config.exists.return_value = True
            write_pyproject_stamp()
            (tmp_path / "core" / "pyproject.toml").write_text("[project]\nname='x'\n")
            assert detect_stale_local_tools() == {"core"}

    def test_tool_missing_from_stamp_is_stale(self, tmp_path: Path) -> None:
        first = self._write_tool(tmp_path, "core", "[project]\nname='core'\n")
        stamp = tmp_path / "stamp.json"
        with (
            patch("llm_prompts.setup.CONFIG_PATH") as mock_config,
            patch("llm_prompts.setup._pyproject_stamp_path", return_value=stamp),
        ):
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=[first]):
                write_pyproject_stamp()
            second = self._write_tool(tmp_path, "hooks", "[project]\nname='hooks'\n")
            with patch("llm_prompts.setup._load_config", return_value=[first, second]):
                assert detect_stale_local_tools() == {"hooks"}


class TestWritePyprojectStamp:
    def test_round_trip(self, tmp_path: Path) -> None:
        repo = tmp_path / "core"
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[project]\nname='core'\n")
        tool = {"name": "core", "source": str(repo)}
        stamp = tmp_path / "sub" / "stamp.json"
        with (
            patch("llm_prompts.setup.CONFIG_PATH") as mock_config,
            patch("llm_prompts.setup._load_config", return_value=[tool]),
            patch("llm_prompts.setup._pyproject_stamp_path", return_value=stamp),
        ):
            mock_config.exists.return_value = True
            write_pyproject_stamp()
            recorded = json.loads(stamp.read_text())
            assert set(recorded) == {"core"}
            assert detect_stale_local_tools() == set()


class TestRunSetupForceReinstall:
    def _run(self, commands: list, force_reinstall: set[str]) -> list[list[str]]:
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
            calls.append(cmd)
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("llm_prompts.setup._load_config", return_value=[]),
            patch("llm_prompts.setup._validate_paths", return_value=[]),
            patch("llm_prompts.setup._detect_installer", return_value="uv"),
            patch("llm_prompts.setup._build_commands", return_value=commands),
            patch("llm_prompts.setup.write_pyproject_stamp"),
            patch("llm_prompts.setup.subprocess.run", side_effect=fake_run),
        ):
            run_setup(force_reinstall=force_reinstall)
        return calls

    def test_forced_core_skips_upgrade(self) -> None:
        commands: list[tuple[str, list[str], list[str] | None, list[str]]] = [
            ("core", ["uv", "install"], ["uv", "upgrade"], [])
        ]
        calls = self._run(commands, {"core"})
        assert calls == [["uv", "install"]]

    def test_stale_overlay_forces_its_core(self) -> None:
        commands = [("core", ["uv", "install"], ["uv", "upgrade"], ["hooks"])]
        calls = self._run(commands, {"hooks"})
        assert calls == [["uv", "install"]]

    def test_unforced_core_uses_upgrade(self) -> None:
        commands: list[tuple[str, list[str], list[str] | None, list[str]]] = [
            ("core", ["uv", "install"], ["uv", "upgrade"], [])
        ]
        calls = self._run(commands, {"other"})
        assert calls[0] == ["uv", "upgrade"]


class TestCheckForUpdates:
    def test_prints_sentinel_when_no_messages(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("llm_prompts.cli._collect_update_messages", return_value=[]):
            result = _check_for_updates()
        assert result is False
        assert capsys.readouterr().out == "All tools are up to date.\n"

    def test_prints_each_message_no_sentinel(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("llm_prompts.cli._collect_update_messages", return_value=["a", "b"]):
            result = _check_for_updates()
        assert result is True
        assert capsys.readouterr().out == "a\nb\n"
