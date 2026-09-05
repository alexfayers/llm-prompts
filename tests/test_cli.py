"""Tests for CLI update check functionality."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import FakeSubprocess

from llm_prompts.cli import (
    _check_for_updates,
    _collect_sources,
    _collect_update_messages,
    _get_installed_commit,
    _local_source_messages,
    _print_parked_state,
    _pull_local_sources,
    _remote_source_messages,
    _restart_memory_service,
    _run_size_check,
    _size_guard_roots,
    main,
)
from llm_prompts.setup import (
    _extract_git_url,
    detect_stale_local_tools,
    run_setup,
    write_pyproject_stamp,
)
from llm_prompts.size_guard import ALLOWANCES_FILENAME, Artifact
from llm_prompts.size_limits import FINALS, RULE_BYTES


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
                (
                    "[pkg] update available:\n"
                    "- Add X\n"
                    "- Fix Y\n"
                    "Summarize these changes for the user in plain language, and flag "
                    "anything that looks like a breaking change."
                )
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
    def test_has_updates_lists_commit_subjects(
        self, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        (tmp_path / ".git").mkdir()
        fake_subprocess.on("rev-list", "--count", stdout="3\n")
        fake_subprocess.on(
            "log",
            "--pretty=format:%s",
            stdout=fake_subprocess.log_lines("Add A", "Fix B", "Tweak C"),
        )
        result = _local_source_messages("core", str(tmp_path))
        assert result == [
            (
                "[core] update available:\n"
                "- Add A\n"
                "- Fix B\n"
                "- Tweak C\n"
                "Summarize these changes for the user in plain language, and flag "
                "anything that looks like a breaking change."
            )
        ]

    def test_up_to_date(self, tmp_path: Path, fake_subprocess: FakeSubprocess) -> None:
        (tmp_path / ".git").mkdir()
        fake_subprocess.on("rev-list", "--count", stdout="0\n")
        result = _local_source_messages("core", str(tmp_path))
        assert result == []

    def test_no_git_dir(self, tmp_path: Path) -> None:
        assert _local_source_messages("core", str(tmp_path)) == []

    def test_rev_list_fails(
        self, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        (tmp_path / ".git").mkdir()
        fake_subprocess.on("rev-list", "--count", returncode=128)
        result = _local_source_messages("core", str(tmp_path))
        assert result == []

    def test_log_failure_falls_back_to_bare_message(
        self, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        (tmp_path / ".git").mkdir()
        fake_subprocess.on("rev-list", "--count", stdout="2\n")
        fake_subprocess.on("log", "--pretty=format:%s", returncode=128)
        result = _local_source_messages("core", str(tmp_path))
        assert result == ["[core] update available"]


class TestPullLocalSources:
    def test_diverged_repo_is_rebased_onto_upstream(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        clone = tmp_path / "clone"
        (clone / ".git").mkdir(parents=True)
        fake_subprocess.on("rev-list", "--count", stdout="1\n")
        fake_subprocess.on("pull", "--ff-only", returncode=1)
        fake_subprocess.on("rebase", "--quiet", returncode=0)

        config = [{"name": "core", "source": str(clone)}]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                _pull_local_sources()

        fake_subprocess.assert_sequence(
            "fetch", "rev-list --count", "pull --ff-only", "rebase --quiet"
        )
        assert (
            "[core] rebased local commits onto 1 new commit(s)"
            in capsys.readouterr().out
        )

    def test_fast_forwardable_repo_is_pulled_without_rebase(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        clone = tmp_path / "clone"
        (clone / ".git").mkdir(parents=True)
        fake_subprocess.on("rev-list", "--count", stdout="1\n")
        fake_subprocess.on("pull", "--ff-only", returncode=0)

        config = [{"name": "core", "source": str(clone)}]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                _pull_local_sources()

        assert fake_subprocess.matching("rebase") == []
        assert "[core] pulled 1 new commit(s)" in capsys.readouterr().out

    def test_conflicting_rebase_is_aborted_and_reported(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        clone = tmp_path / "clone"
        (clone / ".git").mkdir(parents=True)
        fake_subprocess.on("rev-list", "--count", stdout="1\n")
        fake_subprocess.on("pull", "--ff-only", returncode=1)
        fake_subprocess.on("rebase", "--quiet", returncode=1)

        config = [{"name": "core", "source": str(clone)}]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                _pull_local_sources()

        fake_subprocess.assert_sequence(
            "fetch",
            "rev-list --count",
            "pull --ff-only",
            "rebase --quiet",
            "rebase --abort",
        )
        assert "[core] 1 new commit(s) available but rebase failed" in (
            capsys.readouterr().out
        )

    def test_output_lines_preserve_config_order(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        clones = {name: tmp_path / name for name in ("first", "second", "third")}
        for clone in clones.values():
            (clone / ".git").mkdir(parents=True)
        fake_subprocess.on("rev-list", "--count", stdout="1\n")
        fake_subprocess.on("pull", "--ff-only", returncode=0)

        config = [
            {"name": name, "source": str(clone)} for name, clone in clones.items()
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

    def test_only_sources_that_changed_are_reported_as_changed(
        self, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        changed = tmp_path / "changed"
        (changed / ".git").mkdir(parents=True)
        current = tmp_path / "current"
        (current / ".git").mkdir(parents=True)
        fake_subprocess.on("rev-list", "--count", stdout="1\n", repo=changed)
        fake_subprocess.on("rev-list", "--count", stdout="0\n", repo=current)
        fake_subprocess.on("pull", "--ff-only", returncode=0, repo=changed)

        config = [
            {"name": "changed", "source": str(changed)},
            {"name": "current", "source": str(current)},
        ]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                assert _pull_local_sources() == {"changed"}

    def test_rebase_failure_lines_stay_adjacent_and_ordered(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        conflict = tmp_path / "conflict"
        (conflict / ".git").mkdir(parents=True)
        ff = tmp_path / "ff"
        (ff / ".git").mkdir(parents=True)
        fake_subprocess.on("rev-list", "--count", stdout="1\n")
        fake_subprocess.on("pull", "--ff-only", returncode=1, repo=conflict)
        fake_subprocess.on("pull", "--ff-only", returncode=0, repo=ff)
        fake_subprocess.on("rebase", "--quiet", returncode=1, repo=conflict)

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


class TestRestartMemoryService:
    def test_restarts_via_the_mcp_memory_binary(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        with patch("shutil.which", return_value="/usr/local/bin/mcp-memory"):
            _restart_memory_service()

        assert fake_subprocess.calls == [
            (["/usr/local/bin/mcp-memory", "restart"], {"check": False})
        ]

    def test_does_nothing_when_the_binary_is_not_installed(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        with patch("shutil.which", return_value=None):
            _restart_memory_service()

        assert fake_subprocess.calls == []


class TestUpdateRestartsMemoryOnlyWhenItChanged:
    def _run_update(self, changed: set[str]) -> tuple[MagicMock, MagicMock]:
        """Run `llm-prompts update` with the given set of changed sources.

        Returns:
            The patched db-migration and service-restart mocks.
        """
        with (
            patch("sys.argv", ["llm-prompts", "update"]),
            patch(
                "llm_prompts.manifest.read_manifest",
                return_value={"kiro": {"files": []}},
            ),
            patch("llm_prompts.cli._pull_local_sources", return_value=changed),
            patch("llm_prompts.setup.has_remote_sources", return_value=False),
            patch("llm_prompts.setup.detect_stale_local_tools", return_value=set()),
            patch("llm_prompts.setup.run_setup"),
            patch("llm_prompts.install.main"),
            patch("llm_prompts.cli._auto_migrate_memory_db") as mock_migrate,
            patch("llm_prompts.cli._restart_memory_service") as mock_restart,
            patch("llm_prompts.plugins.pull_plugin_sources"),
        ):
            main()
        return mock_migrate, mock_restart

    def test_unrelated_source_change_leaves_the_service_running(self) -> None:
        _, restart = self._run_update({"cline-hooks"})
        restart.assert_not_called()

    def test_memory_source_change_restarts_the_service(self) -> None:
        _, restart = self._run_update({"cline-hooks", "mcp-memory"})
        restart.assert_called_once_with()

    def test_reinstalled_remote_memory_restarts_the_service(self) -> None:
        with (
            patch("sys.argv", ["llm-prompts", "update"]),
            patch(
                "llm_prompts.manifest.read_manifest",
                return_value={"kiro": {"files": []}},
            ),
            patch("llm_prompts.cli._pull_local_sources", return_value=set()),
            patch("llm_prompts.setup.CONFIG_PATH") as mock_config,
            patch("llm_prompts.setup.has_remote_sources", return_value=True),
            patch("llm_prompts.setup.detect_stale_local_tools", return_value=set()),
            patch("llm_prompts.setup.run_setup"),
            patch("llm_prompts.install.main"),
            patch(
                "llm_prompts.cli._get_installed_commit",
                side_effect=["oldcommit", "newcommit"],
            ),
            patch("llm_prompts.cli._auto_migrate_memory_db"),
            patch("llm_prompts.cli._restart_memory_service") as mock_restart,
            patch("llm_prompts.plugins.pull_plugin_sources"),
        ):
            mock_config.exists.return_value = True
            main()

        mock_restart.assert_called_once_with()


class TestUpdateReconfiguresOnlyAfterASuccessfulPull:
    def _run_update(self, changed: set[str]) -> dict[str, MagicMock]:
        """Run `llm-prompts update` with the given set of changed sources.

        Returns:
            The patched post-install configuration mocks, keyed by name.
        """
        with (
            patch("sys.argv", ["llm-prompts", "update"]),
            patch(
                "llm_prompts.manifest.read_manifest",
                return_value={"claude-code": {"files": []}, "codex": {"files": []}},
            ),
            patch("llm_prompts.cli._pull_local_sources", return_value=changed),
            patch("llm_prompts.setup.has_remote_sources", return_value=False),
            patch("llm_prompts.setup.detect_stale_local_tools", return_value=set()),
            patch("llm_prompts.setup.run_setup"),
            patch("llm_prompts.install.main"),
            patch("llm_prompts.cli._get_installed_commit", return_value=None),
            patch("llm_prompts.cli._restart_memory_service"),
            patch("llm_prompts.plugins.pull_plugin_sources"),
            patch("llm_prompts.install.try_install_hooks_claude_code") as hooks,
            patch("llm_prompts.install.try_install_memory_claude_code") as memory,
            patch("llm_prompts.install.try_allow_update_claude_code") as allow,
            patch("llm_prompts.install.try_install_memory_codex") as codex,
            patch("llm_prompts.cli._auto_migrate_memory_db") as migrate,
        ):
            main()
        return {
            "hooks": hooks,
            "memory": memory,
            "allow": allow,
            "codex": codex,
            "migrate": migrate,
        }

    def test_nothing_pulled_leaves_every_agent_config_untouched(self) -> None:
        mocks = self._run_update(set())
        for mock in mocks.values():
            mock.assert_not_called()

    def test_a_pulled_source_reconfigures_the_agents(self) -> None:
        mocks = self._run_update({"cline-hooks"})
        mocks["hooks"].assert_called_once_with()
        mocks["allow"].assert_called_once_with()

    def test_memory_config_and_db_wait_for_a_memory_change(self) -> None:
        mocks = self._run_update({"cline-hooks"})
        mocks["memory"].assert_not_called()
        mocks["codex"].assert_not_called()
        mocks["migrate"].assert_not_called()

    def test_a_memory_change_reconfigures_memory_and_migrates_the_db(self) -> None:
        mocks = self._run_update({"mcp-memory"})
        mocks["memory"].assert_called_once_with()
        mocks["codex"].assert_called_once_with()
        mocks["migrate"].assert_called_once_with()


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

        with (
            patch("llm_prompts.cli._get_root_dir", return_value=base),
            patch(
                "llm_prompts.install._discover_overlay_paths",
                return_value=[overlay],
            ),
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

        with (
            patch("llm_prompts.cli._get_root_dir", return_value=base),
            patch(
                "llm_prompts.install._discover_overlay_paths",
                return_value=[overlay],
            ),
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
    def _run(
        self,
        fake_subprocess: FakeSubprocess,
        commands: list[tuple[str, list[str], list[str] | None, list[str]]],
        force_reinstall: set[str],
    ) -> list[list[str]]:
        with (
            patch("llm_prompts.setup._load_config", return_value=[]),
            patch("llm_prompts.setup._validate_paths", return_value=[]),
            patch("llm_prompts.setup._detect_installer", return_value="uv"),
            patch("llm_prompts.setup._build_commands", return_value=commands),
            patch("llm_prompts.setup.write_pyproject_stamp"),
        ):
            run_setup(force_reinstall=force_reinstall)
        return fake_subprocess.commands

    def test_forced_core_skips_upgrade(self, fake_subprocess: FakeSubprocess) -> None:
        commands: list[tuple[str, list[str], list[str] | None, list[str]]] = [
            ("core", ["uv", "install"], ["uv", "upgrade"], [])
        ]
        calls = self._run(fake_subprocess, commands, {"core"})
        assert calls == [["uv", "install"]]

    def test_stale_overlay_forces_its_core(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        commands: list[tuple[str, list[str], list[str] | None, list[str]]] = [
            ("core", ["uv", "install"], ["uv", "upgrade"], ["hooks"])
        ]
        calls = self._run(fake_subprocess, commands, {"hooks"})
        assert calls == [["uv", "install"]]

    def test_unforced_core_uses_upgrade(self, fake_subprocess: FakeSubprocess) -> None:
        commands: list[tuple[str, list[str], list[str] | None, list[str]]] = [
            ("core", ["uv", "install"], ["uv", "upgrade"], [])
        ]
        calls = self._run(fake_subprocess, commands, {"other"})
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


class TestSizeGuardRoots:
    def test_includes_own_root_and_discovered_overlays(self, tmp_path: Path) -> None:
        own_root = tmp_path / "own"
        overlay_root = tmp_path / "overlay"
        with (
            patch("llm_prompts.cli._get_root_dir", return_value=own_root),
            patch(
                "llm_prompts.install._discover_overlay_paths",
                return_value=[overlay_root],
            ),
        ):
            roots = _size_guard_roots()
        assert roots == [own_root, overlay_root]


class TestPrintParkedState:
    def test_no_artifacts_over_final_prints_nothing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        artifact = Artifact(RULE_BYTES, "claude-code", "a.md", 10, Path("a.md"))
        _print_parked_state([artifact])
        assert capsys.readouterr().out == ""

    def test_over_final_artifacts_grouped_by_metric(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        final = FINALS[RULE_BYTES]
        artifacts = [
            Artifact(RULE_BYTES, "claude-code", "a.md", final + 100, Path("a.md")),
            Artifact(RULE_BYTES, "claude-code", "b.md", final + 5_000, Path("b.md")),
        ]
        _print_parked_state(artifacts)
        out = capsys.readouterr().out
        assert f"current {final + 5_000:,}" in out
        assert f"final {final:,}" in out
        assert "2 files awaiting compression" in out


class TestRunSizeCheck:
    def test_clean_tree_passes_and_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "root"
        (root / "shared" / "rules").mkdir(parents=True)
        (root / "shared" / "rules" / "a.md").write_text("# A\n", encoding="utf-8")
        for target in ("claude-code", "copilot", "kiro"):
            target_dir = root / target
            target_dir.mkdir(parents=True)
            (target_dir / "vars.json").write_text("{}", encoding="utf-8")

        with patch("llm_prompts.cli._size_guard_roots", return_value=[root]):
            _run_size_check()

        assert "All prompt-size checks passed." in capsys.readouterr().out

    def test_oversized_artifact_exits_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "root"
        (root / "shared" / "rules").mkdir(parents=True)
        (root / "shared" / "rules" / "big.md").write_text(
            "x " * FINALS[RULE_BYTES], encoding="utf-8"
        )
        for target in ("claude-code", "copilot", "kiro"):
            target_dir = root / target
            target_dir.mkdir(parents=True)
            (target_dir / "vars.json").write_text("{}", encoding="utf-8")

        with (
            patch("llm_prompts.cli._size_guard_roots", return_value=[root]),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run_size_check()

        assert exc_info.value.code == 1
        assert "big.md" in capsys.readouterr().out

    def test_stale_allowance_prints_on_a_passing_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "root"
        (root / "shared" / "rules").mkdir(parents=True)
        (root / "shared" / "rules" / "a.md").write_text("# A\n", encoding="utf-8")
        for target in ("claude-code", "copilot", "kiro"):
            target_dir = root / target
            target_dir.mkdir(parents=True)
            (target_dir / "vars.json").write_text("{}", encoding="utf-8")
        (root / ALLOWANCES_FILENAME).write_text(
            json.dumps({RULE_BYTES: {"nonexistent.md": 1_000}}), encoding="utf-8"
        )

        with patch("llm_prompts.cli._size_guard_roots", return_value=[root]):
            _run_size_check()

        assert "nonexistent.md" in capsys.readouterr().out

    def test_declaration_error_exits_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "root"
        (root / "shared" / "rules").mkdir(parents=True)
        (root / "shared" / "rules" / "a.md").write_text("# A\n", encoding="utf-8")
        for target in ("claude-code", "copilot", "kiro"):
            target_dir = root / target
            target_dir.mkdir(parents=True)
            (target_dir / "vars.json").write_text("{}", encoding="utf-8")
        (root / ALLOWANCES_FILENAME).write_text(
            json.dumps({"not_a_metric": {"a": 1}}), encoding="utf-8"
        )

        with (
            patch("llm_prompts.cli._size_guard_roots", return_value=[root]),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run_size_check()

        assert exc_info.value.code == 1
        assert "not_a_metric" in capsys.readouterr().out


class TestCheckSubcommand:
    def test_check_dispatches_to_run_size_check(self) -> None:
        with (
            patch("sys.argv", ["llm-prompts", "check"]),
            patch("llm_prompts.cli._run_size_check") as mock_check,
        ):
            main()
        mock_check.assert_called_once_with()
