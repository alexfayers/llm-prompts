"""Tests for the uninstall teardown functions in install.py."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import FakeSubprocess

from llm_prompts.cli import main
from llm_prompts.install import (
    _disallow_update_claude_code,
    _kiro_resources,
    _pi_agent_dir,
    _remove_cline_symlinks,
    _remove_manifest_files,
    _unpatch_kiro_agent_config,
    try_install_memory,
    try_install_memory_claude_code,
    try_install_memory_pi,
    uninstall,
)
from llm_prompts.install import main as install_main
from llm_prompts.manifest import read_manifest, write_manifest


class TestRemoveManifestFiles:
    def test_removes_files_and_directory(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.md"
        f1.write_text("x", encoding="utf-8")
        d1 = tmp_path / "skills" / "foo"
        d1.mkdir(parents=True)
        (d1 / "SKILL.md").write_text("y", encoding="utf-8")

        _remove_manifest_files("kiro", [str(f1), str(d1)])

        assert not f1.exists()
        assert not d1.exists()

    def test_nonexistent_path_is_noop(self, tmp_path: Path) -> None:
        _remove_manifest_files("kiro", [str(tmp_path / "gone.md")])


class TestRemoveClineSymlinks:
    def test_removes_symlinks(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        real = tmp_path / "real"
        real.mkdir()
        with patch("llm_prompts.install.Path.home", return_value=home):
            from llm_prompts.install import _get_cline_symlinks

            symlinks = _get_cline_symlinks()
            for dest in symlinks:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(real)

            _remove_cline_symlinks()

            for dest in symlinks:
                assert not dest.exists()
                assert not dest.is_symlink()

    def test_leaves_real_directory_untouched(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            from llm_prompts.install import _get_cline_symlinks

            rules_dest = _get_cline_symlinks()[0]
            rules_dest.mkdir(parents=True)
            (rules_dest / "keep.md").write_text("mine", encoding="utf-8")

            _remove_cline_symlinks()

            assert rules_dest.is_dir()
            assert (rules_dest / "keep.md").exists()


class TestUnpatchKiroAgentConfig:
    def test_removes_only_kiro_resources(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            resources = _kiro_resources()
            config_path = tmp_path / "agent.json"
            config_path.write_text(
                json.dumps({"resources": [*resources, "file:///other.md"]}),
                encoding="utf-8",
            )

            _unpatch_kiro_agent_config(str(config_path))

            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["resources"] == ["file:///other.md"]

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        _unpatch_kiro_agent_config(str(tmp_path / "gone.json"))


class TestDisallowUpdateClaudeCode:
    def _write_settings(self, home: Path, allow: list[str]) -> Path:
        settings_path = home / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps({"permissions": {"allow": allow}}), encoding="utf-8"
        )
        return settings_path

    def test_removes_rule_keeps_others(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            settings_path = self._write_settings(
                home, ["Bash(llm-prompts update *)", "Bash(ls *)"]
            )

            _disallow_update_claude_code()

            data = json.loads(settings_path.read_text(encoding="utf-8"))
            assert data["permissions"]["allow"] == ["Bash(ls *)"]

    def test_missing_settings_is_noop(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            _disallow_update_claude_code()

    def test_rule_absent_is_noop(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            settings_path = self._write_settings(home, ["Bash(ls *)"])

            _disallow_update_claude_code()

            data = json.loads(settings_path.read_text(encoding="utf-8"))
            assert data["permissions"]["allow"] == ["Bash(ls *)"]


@pytest.fixture
def installed_home(tmp_path: Path, synthetic_prompts: Path) -> Iterator[Path]:
    """Run `install claude-code` into a fake home with overlays/manifest redirected."""
    home = tmp_path / "home"
    home.mkdir()
    with (
        patch("llm_prompts.install.Path.home", return_value=home),
        patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
    ):
        install_main(["claude-code"])
        yield home


class TestUninstallEndToEnd:
    def test_uninstall_single_agent_removes_files_and_manifest(
        self, installed_home: Path, tmp_path: Path
    ) -> None:
        with (
            patch("llm_prompts.install.Path.home", return_value=installed_home),
        ):
            entry = read_manifest()["claude-code"]
            assert entry["files"]
            assert all(Path(f).exists() for f in entry["files"])

            uninstall(["claude-code"])

            assert "claude-code" not in read_manifest()
            assert all(not Path(f).exists() for f in entry["files"])

    def test_uninstall_not_installed_warns_and_preserves_others(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
        ):
            write_manifest("kiro", [str(home / "keep.md")])

            uninstall(["codex"])

            assert "kiro" in read_manifest()

    def test_uninstall_all_removes_every_agent(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
        ):
            write_manifest("kiro", [])
            write_manifest("codex", [])

            uninstall(None)

            assert read_manifest() == {}


class TestUninstallRemovedAgents:
    def test_cli_accepts_a_removed_agent(self) -> None:
        with (
            patch("sys.argv", ["llm-prompts", "uninstall", "cline"]),
            patch("llm_prompts.install.uninstall") as mock_uninstall,
        ):
            main()

        mock_uninstall.assert_called_once_with(["cline"], verbose=False)


_TEARDOWN_HELP = "--agent AGENT --keep-service --kiro-agent-config PATH"


@pytest.fixture
def companion_tools(
    fake_subprocess: FakeSubprocess, real_teardown: None
) -> Iterator[FakeSubprocess]:
    """Route the `cline-hook` and `mcp-memory` calls to fake_subprocess, with a scoped memory teardown."""
    fake_subprocess.on("mcp-memory", "teardown", "--help", stdout=_TEARDOWN_HELP)
    with patch("llm_prompts.install.user_binary", side_effect=lambda name: name):
        yield fake_subprocess


def _teardown_calls(fake: FakeSubprocess) -> list[str]:
    return [
        " ".join(argv)
        for argv in fake.commands
        if "--help" not in argv and argv[1] in ("uninstall", "teardown")
    ]


def _install_memory(service_exists: bool, *agents: str) -> None:
    with patch(
        "llm_prompts.install._memory_service_exists", return_value=service_exists
    ):
        for agent in agents:
            write_manifest(agent, [])
            {
                "claude-code": try_install_memory_claude_code,
                "pi": try_install_memory_pi,
            }[agent]()


class TestUninstallCompanionTools:
    def test_tears_down_what_install_set_up_with_the_last_agent(
        self, companion_tools: FakeSubprocess, tmp_path: Path
    ) -> None:
        configs = [str(tmp_path / "one.json"), str(tmp_path / "two.json")]
        _install_memory(False, "claude-code")
        for name, config in zip(("kiro", "codex"), configs, strict=True):
            write_manifest(name, [], agent_config=config)
            try_install_memory(config)

        uninstall(None)

        assert _teardown_calls(companion_tools) == [
            "cline-hook uninstall claude-code",
            f"cline-hook uninstall kiro {configs[0]}",
            f"cline-hook uninstall kiro {configs[1]}",
            (
                "mcp-memory teardown --agent claude-code --agent kiro"
                f" --kiro-agent-config {configs[0]} --kiro-agent-config {configs[1]}"
            ),
        ]

    def test_keeps_a_service_that_existed_before_install(
        self, companion_tools: FakeSubprocess
    ) -> None:
        _install_memory(True, "claude-code")

        uninstall(None)

        assert _teardown_calls(companion_tools)[-1] == (
            "mcp-memory teardown --agent claude-code --keep-service"
        )

    def test_keeps_the_service_while_a_memory_agent_stays_installed(
        self, companion_tools: FakeSubprocess
    ) -> None:
        _install_memory(False, "claude-code", "pi")

        uninstall(["claude-code"])

        assert _teardown_calls(companion_tools) == [
            "cline-hook uninstall claude-code",
            "mcp-memory teardown --agent claude-code --keep-service",
        ]

    def test_runs_the_pi_hook_teardown_against_the_pi_agent_dir(
        self, companion_tools: FakeSubprocess
    ) -> None:
        write_manifest("pi", [])

        uninstall(None)

        (call,) = [
            kwargs
            for argv, kwargs in companion_tools.calls
            if argv == ["cline-hook", "uninstall", "pi"]
        ]
        assert call["env"]["PI_CODING_AGENT_DIR"] == str(_pi_agent_dir())

    def test_retries_a_memory_teardown_skipped_for_missing_flags(
        self, companion_tools: FakeSubprocess
    ) -> None:
        companion_tools.on(
            "mcp-memory",
            "teardown",
            "--help",
            stdout=["--kiro-agent-config --agents --keep-services", _TEARDOWN_HELP],
        )
        _install_memory(True, "claude-code")

        with patch("llm_prompts.install.log") as mock_log:
            uninstall(None)
        uninstall(None)

        mock_log.assert_any_call(
            "warn",
            "mcp-memory teardown lacks --agent, --keep-service, skipped it. Update"
            " mcp-memory, then run `mcp-memory teardown --agent claude-code"
            " --keep-service`.",
        )
        assert _teardown_calls(companion_tools) == [
            "cline-hook uninstall claude-code",
            "mcp-memory teardown --agent claude-code --keep-service",
        ]

    def test_reports_a_failing_teardown(self, companion_tools: FakeSubprocess) -> None:
        companion_tools.on("cline-hook", "uninstall", "claude-code", returncode=3)
        companion_tools.on("cline-hook", "uninstall", "claude-code", "--help")
        write_manifest("claude-code", [])

        with patch("llm_prompts.install.log") as mock_log:
            uninstall(None)

        mock_log.assert_any_call(
            "error", "`cline-hook uninstall claude-code` failed with exit code 3."
        )

    def test_skips_tools_without_a_teardown_command(
        self, companion_tools: FakeSubprocess
    ) -> None:
        companion_tools.on("cline-hook", returncode=2)
        companion_tools.on("mcp-memory", "teardown", "--help", returncode=2)
        _install_memory(False, "claude-code")

        with patch("llm_prompts.install.log") as mock_log:
            uninstall(None)

        assert _teardown_calls(companion_tools) == []
        mock_log.assert_any_call(
            "warn",
            "mcp-memory has no `teardown` command, skipped it. Update mcp-memory,"
            " then run `mcp-memory teardown --agent claude-code`.",
        )

    def test_skips_missing_tools(
        self, fake_subprocess: FakeSubprocess, real_teardown: None
    ) -> None:
        write_manifest("claude-code", [])

        with patch("llm_prompts.install.user_binary", return_value=None):
            uninstall(None)

        assert fake_subprocess.commands == []

    def test_runs_nothing_when_nothing_was_installed(
        self, companion_tools: FakeSubprocess
    ) -> None:
        uninstall(None)

        assert _teardown_calls(companion_tools) == []
