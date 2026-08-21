"""Tests for the auto-reinstall cline-hooks plugin."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from llm_prompts.hooks import (
    _ANSI_COLOR,
    _ANSI_RESET,
    _BANNER_DIVIDER,
    _BANNER_TITLE,
    _DEBOUNCE_SECONDS,
    _UPDATE_CHECK_INTERVAL,
    AutoReinstallPlugin,
    _format_user_text,
    _ReinstallDebouncer,
    _strip_update_instruction,
)
from llm_prompts.setup import _UPDATE_INSTRUCTION


@pytest.fixture
def manifest_data(tmp_path: Path) -> dict[str, Any]:
    """Create temporary installed files and return manifest data."""
    steering_file = tmp_path / "steering" / "coding.md"
    steering_file.parent.mkdir(parents=True)
    steering_file.write_text("# Coding guidelines")

    skill_file = tmp_path / "skills" / "git-usage" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("# Git usage")

    return {
        "kiro": {
            "files": [str(steering_file), str(skill_file)],
            "installed_at": "2026-01-01T00:00:00+00:00",
        },
    }


@pytest.fixture
def plugin(manifest_data: dict[str, Any], tmp_path: Path) -> AutoReinstallPlugin:
    """Create a plugin with pre-loaded manifest paths."""
    p = AutoReinstallPlugin()
    p._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
    with patch("llm_prompts.hooks.read_manifest", return_value=manifest_data):
        p._get_installed_paths()
    return p


class TestStripUpdateInstruction:
    """Tests for stripping the trailing model-directive instruction."""

    def test_strips_instruction_and_preceding_newline(self) -> None:
        original = "[pkg] update available:\n- did a thing\n" + _UPDATE_INSTRUCTION
        assert _strip_update_instruction(original) == (
            "[pkg] update available:\n- did a thing"
        )

    def test_noop_on_bare_fallback(self) -> None:
        bare = "[pkg] update available"
        assert _strip_update_instruction(bare) == bare


class TestFormatUserText:
    """Tests for wrapping update text in a banner header/footer."""

    def test_wraps_with_banner_and_blank_lines(self) -> None:
        formatted = _format_user_text("[pkg] update available:\n- did a thing")
        assert formatted == (
            "\n"
            f"{_ANSI_COLOR}{_BANNER_DIVIDER}\n"
            f"{_BANNER_TITLE}\n"
            f"{_BANNER_DIVIDER}{_ANSI_RESET}\n"
            "\n"
            "[pkg] update available:\n- did a thing\n"
            "\n"
            f"{_ANSI_COLOR}{_BANNER_DIVIDER}{_ANSI_RESET}"
        )


class TestReinstallDebouncer:
    """Tests for the debounce mechanism."""

    def test_should_run_initially(self, tmp_path: Path) -> None:
        assert _ReinstallDebouncer(tmp_path / "stamp").should_run()

    def test_should_not_run_immediately_after(self, tmp_path: Path) -> None:
        debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        debouncer.mark_run()
        assert not debouncer.should_run()

    def test_should_run_after_debounce_period(self, tmp_path: Path) -> None:
        debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        (tmp_path / "stamp").write_text(str(time.time() - 10.0))
        assert debouncer.should_run()

    def test_respects_custom_interval(self, tmp_path: Path) -> None:
        d = _ReinstallDebouncer(tmp_path / "stamp", interval_seconds=100.0)
        d.mark_run()
        assert not d.should_run()
        (tmp_path / "stamp").write_text(str(time.time() - 50))
        assert not d.should_run()
        (tmp_path / "stamp").write_text(str(time.time() - 150))
        assert d.should_run()


class TestAutoReinstallPlugin:
    """Tests for the AutoReinstallPlugin."""

    def test_ignores_non_post_tool_use(self, plugin: AutoReinstallPlugin) -> None:
        assert plugin.on_hook("PreToolUse", tool_name="write_to_file") is None

    def test_ignores_non_write_tools(self, plugin: AutoReinstallPlugin) -> None:
        assert (
            plugin.on_hook(
                "PostToolUse",
                tool_name="read_file",
                parameters={"path": "/some/file"},
            )
            is None
        )

    def test_ignores_unmanaged_files(
        self,
        plugin: AutoReinstallPlugin,
        tmp_path: Path,
    ) -> None:
        unmanaged = tmp_path / "random" / "file.txt"
        unmanaged.parent.mkdir(parents=True)
        unmanaged.write_text("hello")
        assert (
            plugin.on_hook(
                "PostToolUse",
                tool_name="write_to_file",
                parameters={"path": str(unmanaged)},
            )
            is None
        )

    def test_ignores_missing_path_parameter(self, plugin: AutoReinstallPlugin) -> None:
        assert (
            plugin.on_hook("PostToolUse", tool_name="write_to_file", parameters={})
            is None
        )

    def test_ignores_non_dict_parameters(self, plugin: AutoReinstallPlugin) -> None:
        assert (
            plugin.on_hook("PostToolUse", tool_name="write_to_file", parameters="bad")
            is None
        )

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.hooks.read_manifest")
    def test_triggers_reinstall_for_managed_file(
        self,
        mock_manifest: MagicMock,
        mock_run: MagicMock,
        manifest_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        mock_manifest.return_value = manifest_data
        mock_run.return_value.returncode = 0
        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        result = plugin.on_hook(
            "PostToolUse",
            tool_name="write_to_file",
            parameters={"path": manifest_data["kiro"]["files"][0]},
        )
        assert result is not None
        assert any("Auto-reinstalled" in note for note in result.notes)
        mock_run.assert_called_once()

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.hooks.read_manifest")
    def test_triggers_reinstall_for_claude_code_edit(
        self,
        mock_manifest: MagicMock,
        mock_run: MagicMock,
        manifest_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        mock_manifest.return_value = manifest_data
        mock_run.return_value.returncode = 0
        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        result = plugin.on_hook(
            "PostToolUse",
            tool_name="Edit",
            parameters={"file_path": manifest_data["kiro"]["files"][0]},
        )
        assert result is not None
        assert any("Auto-reinstalled" in note for note in result.notes)
        mock_run.assert_called_once()

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.hooks.read_manifest")
    def test_triggers_reinstall_for_claude_code_write(
        self,
        mock_manifest: MagicMock,
        mock_run: MagicMock,
        manifest_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        mock_manifest.return_value = manifest_data
        mock_run.return_value.returncode = 0
        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        result = plugin.on_hook(
            "PostToolUse",
            tool_name="Write",
            parameters={"file_path": manifest_data["kiro"]["files"][1]},
        )
        assert result is not None
        assert any("Auto-reinstalled" in note for note in result.notes)
        mock_run.assert_called_once()

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.hooks.read_manifest")
    def test_reports_failure_on_nonzero_exit(
        self,
        mock_manifest: MagicMock,
        mock_run: MagicMock,
        manifest_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        mock_manifest.return_value = manifest_data
        mock_run.return_value.returncode = 1
        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        result = plugin.on_hook(
            "PostToolUse",
            tool_name="write_to_file",
            parameters={"path": manifest_data["kiro"]["files"][0]},
        )
        assert result is not None
        assert result.notes == ["Failed to auto-reinstall prompt files"]

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.hooks.read_manifest")
    def test_debounces_rapid_writes(
        self,
        mock_manifest: MagicMock,
        mock_run: MagicMock,
        manifest_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        mock_manifest.return_value = manifest_data
        mock_run.return_value.returncode = 0
        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        path = manifest_data["kiro"]["files"][0]

        result1 = plugin.on_hook(
            "PostToolUse", tool_name="write_to_file", parameters={"path": path}
        )
        assert result1 is not None

        result2 = plugin.on_hook(
            "PostToolUse", tool_name="write_to_file", parameters={"path": path}
        )
        assert result2 is None

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.hooks.read_manifest")
    def test_flushes_debounced_write_on_later_hook(
        self,
        mock_manifest: MagicMock,
        mock_run: MagicMock,
        manifest_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        mock_manifest.return_value = manifest_data
        mock_run.return_value.returncode = 0
        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        path = manifest_data["kiro"]["files"][0]

        plugin.on_hook(
            "PostToolUse", tool_name="write_to_file", parameters={"path": path}
        )
        assert (
            plugin.on_hook(
                "PostToolUse", tool_name="write_to_file", parameters={"path": path}
            )
            is None
        )
        (tmp_path / "stamp").write_text(str(time.time() - _DEBOUNCE_SECONDS - 1))

        result = plugin.on_hook(
            "PostToolUse", tool_name="read_file", parameters={"path": path}
        )
        assert result is not None
        assert any("Auto-reinstalled" in note for note in result.notes)
        assert mock_run.call_count == 2

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.hooks.read_manifest")
    def test_holds_pending_flush_until_interval_elapses(
        self,
        mock_manifest: MagicMock,
        mock_run: MagicMock,
        manifest_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        mock_manifest.return_value = manifest_data
        mock_run.return_value.returncode = 0
        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        path = manifest_data["kiro"]["files"][0]

        plugin.on_hook(
            "PostToolUse", tool_name="write_to_file", parameters={"path": path}
        )
        plugin.on_hook(
            "PostToolUse", tool_name="write_to_file", parameters={"path": path}
        )

        assert (
            plugin.on_hook(
                "PostToolUse", tool_name="read_file", parameters={"path": path}
            )
            is None
        )
        assert mock_run.call_count == 1

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.hooks.read_manifest")
    def test_invalidates_cache_after_reinstall(
        self,
        mock_manifest: MagicMock,
        mock_run: MagicMock,
        manifest_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        mock_manifest.return_value = manifest_data
        mock_run.return_value.returncode = 0
        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        plugin.on_hook(
            "PostToolUse",
            tool_name="write_to_file",
            parameters={"path": manifest_data["kiro"]["files"][0]},
        )
        assert plugin._installed_paths is None


class TestUpdateCheckOnTaskStart:
    """Tests for the TaskStart update-check dispatch."""

    def test_task_start_reports_updates(self, tmp_path: Path) -> None:
        plugin = AutoReinstallPlugin()
        plugin._update_check_debouncer = _ReinstallDebouncer(
            tmp_path / "update-stamp", interval_seconds=_UPDATE_CHECK_INTERVAL
        )
        message = "[pkg] update available:\n- did a thing\n" + _UPDATE_INSTRUCTION
        with patch(
            "llm_prompts.cli._collect_update_messages",
            return_value=[message],
        ):
            result = plugin.on_hook("TaskStart", task_id="t1", workspace_roots=[])
        assert result is not None
        assert result.notes == [message]
        assert len(result.user_notes) == 1
        note = result.user_notes[0]
        assert note.user_text == _format_user_text(
            "[pkg] update available:\n- did a thing"
        )
        assert (tmp_path / "update-stamp").exists()

    def test_multiple_messages_produce_single_banner(self, tmp_path: Path) -> None:
        plugin = AutoReinstallPlugin()
        plugin._update_check_debouncer = _ReinstallDebouncer(
            tmp_path / "update-stamp", interval_seconds=_UPDATE_CHECK_INTERVAL
        )
        messages = [
            "[pkg-a] update available:\n- did a thing",
            "[pkg-b] not cloned (run `llm-prompts update`)",
        ]
        with patch(
            "llm_prompts.cli._collect_update_messages",
            return_value=messages,
        ):
            result = plugin.on_hook("TaskStart", task_id="t1", workspace_roots=[])
        assert result is not None
        assert result.notes == messages
        assert len(result.user_notes) == 1
        note = result.user_notes[0]
        assert note.user_text == _format_user_text("\n\n".join(messages))
        assert note.user_text.count(_BANNER_TITLE) == 1

    def test_task_start_no_updates_marks_stamp(self, tmp_path: Path) -> None:
        plugin = AutoReinstallPlugin()
        plugin._update_check_debouncer = _ReinstallDebouncer(
            tmp_path / "update-stamp", interval_seconds=_UPDATE_CHECK_INTERVAL
        )
        with patch("llm_prompts.cli._collect_update_messages", return_value=[]):
            result = plugin.on_hook("TaskStart", task_id="t1", workspace_roots=[])
        assert result is None
        assert (tmp_path / "update-stamp").exists()

    def test_task_start_debounced(self, tmp_path: Path) -> None:
        plugin = AutoReinstallPlugin()
        plugin._update_check_debouncer = _ReinstallDebouncer(
            tmp_path / "update-stamp", interval_seconds=_UPDATE_CHECK_INTERVAL
        )
        (tmp_path / "update-stamp").write_text(str(time.time()))
        with patch("llm_prompts.cli._collect_update_messages") as mock_collect:
            result = plugin.on_hook(
                "TaskStart", task_id="t1", workspace_roots=[], source="resume"
            )
        assert result is None
        mock_collect.assert_not_called()

    def test_task_start_check_failure_does_not_mark(self, tmp_path: Path) -> None:
        plugin = AutoReinstallPlugin()
        plugin._update_check_debouncer = _ReinstallDebouncer(
            tmp_path / "update-stamp", interval_seconds=_UPDATE_CHECK_INTERVAL
        )
        with patch(
            "llm_prompts.cli._collect_update_messages",
            side_effect=Exception("boom"),
        ):
            result = plugin.on_hook("TaskStart", task_id="t1", workspace_roots=[])
        assert result is None
        assert not (tmp_path / "update-stamp").exists()

    def test_task_start_survives_system_exit(self, tmp_path: Path) -> None:
        plugin = AutoReinstallPlugin()
        plugin._update_check_debouncer = _ReinstallDebouncer(
            tmp_path / "update-stamp", interval_seconds=_UPDATE_CHECK_INTERVAL
        )
        with patch(
            "llm_prompts.cli._collect_update_messages",
            side_effect=SystemExit(1),
        ):
            result = plugin.on_hook("TaskStart", task_id="t1", workspace_roots=[])
        assert result is None
        assert not (tmp_path / "update-stamp").exists()

    def test_debouncers_are_independent(self) -> None:
        plugin = AutoReinstallPlugin()
        assert plugin._debouncer._stamp != plugin._update_check_debouncer._stamp
        assert plugin._debouncer._interval_seconds == _DEBOUNCE_SECONDS
        assert (
            plugin._update_check_debouncer._interval_seconds == _UPDATE_CHECK_INTERVAL
        )

    def test_fresh_start_bypasses_debounce(self, tmp_path: Path) -> None:
        plugin = AutoReinstallPlugin()
        plugin._update_check_debouncer = _ReinstallDebouncer(
            tmp_path / "update-stamp", interval_seconds=_UPDATE_CHECK_INTERVAL
        )
        (tmp_path / "update-stamp").write_text(str(time.time()))
        with patch(
            "llm_prompts.cli._collect_update_messages",
            return_value=["[pkg] update available (a -> b)"],
        ):
            result = plugin.on_hook(
                "TaskStart", task_id="t1", workspace_roots=[], source=""
            )
        assert result is not None
        assert result.notes == ["[pkg] update available (a -> b)"]
        assert len(result.user_notes) == 1
        note = result.user_notes[0]
        assert note.user_text == _format_user_text("[pkg] update available (a -> b)")

    def test_resume_source_still_debounced(self, tmp_path: Path) -> None:
        plugin = AutoReinstallPlugin()
        plugin._update_check_debouncer = _ReinstallDebouncer(
            tmp_path / "update-stamp", interval_seconds=_UPDATE_CHECK_INTERVAL
        )
        (tmp_path / "update-stamp").write_text(str(time.time()))
        with patch("llm_prompts.cli._collect_update_messages") as mock_collect:
            result = plugin.on_hook(
                "TaskStart", task_id="t1", workspace_roots=[], source="resume"
            )
        assert result is None
        mock_collect.assert_not_called()

    def test_subagent_task_start_skips_check(self, tmp_path: Path) -> None:
        plugin = AutoReinstallPlugin()
        plugin._update_check_debouncer = _ReinstallDebouncer(
            tmp_path / "update-stamp", interval_seconds=_UPDATE_CHECK_INTERVAL
        )
        with patch("llm_prompts.cli._collect_update_messages") as mock_collect:
            result = plugin.on_hook(
                "TaskStart",
                task_id="t1",
                workspace_roots=[],
                source="",
                agent_type="Explore",
            )
        assert result is None
        mock_collect.assert_not_called()
        assert not (tmp_path / "update-stamp").exists()
