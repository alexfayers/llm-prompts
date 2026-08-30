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
    _looks_like_prompt_source,
    _ReinstallDebouncer,
    _strip_update_instruction,
)
from llm_prompts.setup import _UPDATE_INSTRUCTION
from llm_prompts.size_guard import CHECKED_TARGETS, CheckResult, Violation
from llm_prompts.size_limits import FINALS, RULE_BYTES


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


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
        mock_run.return_value.stderr = ""
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
    def test_failure_note_includes_captured_stderr(
        self,
        mock_manifest: MagicMock,
        mock_run: MagicMock,
        manifest_data: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        mock_manifest.return_value = manifest_data
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "size guard: rule.md exceeds final\n"
        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        result = plugin.on_hook(
            "PostToolUse",
            tool_name="write_to_file",
            parameters={"path": manifest_data["kiro"]["files"][0]},
        )
        assert result is not None
        assert result.notes == [
            (
                "Failed to auto-reinstall prompt files:\n"
                "size guard: rule.md exceeds final"
            ),
        ]

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


class TestPromptSizeGate:
    """Tests for the PreToolUse prompt-size gate added by `_gate_edit`."""

    def test_write_breaching_threshold_is_denied(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        root = tmp_path / "size-root"
        for target in CHECKED_TARGETS:
            _write(root / target / "vars.json", "{}")
        path = root / "shared" / "rules" / "big.md"
        content = "x" * (FINALS[RULE_BYTES] + 50) + "\n"

        with patch("llm_prompts.size_guard._own_root_dir", return_value=root):
            result = plugin.on_hook(
                "PreToolUse",
                tool_name="Write",
                parameters={"path": str(path), "content": content},
            )

        assert result is not None
        assert result.block is not None
        assert RULE_BYTES in result.block
        assert "big.md" in result.block
        assert str(FINALS[RULE_BYTES]) in result.block

    def test_write_within_thresholds_returns_none_and_measures_once(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        passing = CheckResult(passed=True, artifacts=[], violations=[], report="ok")
        with patch(
            "llm_prompts.size_guard.check_source", return_value=passing
        ) as mock_check:
            result = plugin.on_hook(
                "PreToolUse",
                tool_name="Write",
                parameters={
                    "path": str(tmp_path / "shared" / "rules" / "small.md"),
                    "content": "fine",
                },
            )

        assert result is None
        mock_check.assert_called_once()

    def test_edit_growing_an_already_violating_file_is_denied(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        path = _write(tmp_path / "shared" / "rules" / "big.md", "old text")
        predicted = CheckResult(
            passed=False,
            artifacts=[],
            violations=[
                Violation(RULE_BYTES, "claude-code", "big.md", 6_000, 5_000, path)
            ],
            report="predicted",
        )
        current = CheckResult(
            passed=False,
            artifacts=[],
            violations=[
                Violation(RULE_BYTES, "claude-code", "big.md", 5_500, 5_000, path)
            ],
            report="current",
        )

        with patch(
            "llm_prompts.size_guard.check_source", side_effect=[predicted, current]
        ):
            result = plugin.on_hook(
                "PreToolUse",
                tool_name="Edit",
                parameters={
                    "path": str(path),
                    "old_string": "old text",
                    "new_string": "much longer new text",
                },
            )

        assert result is not None
        assert result.block is not None

    def test_edit_shrinking_an_already_violating_file_is_allowed(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        path = _write(tmp_path / "shared" / "rules" / "big.md", "old long text")
        predicted = CheckResult(
            passed=False,
            artifacts=[],
            violations=[
                Violation(RULE_BYTES, "claude-code", "big.md", 4_800, 5_000, path)
            ],
            report="predicted",
        )
        current = CheckResult(
            passed=False,
            artifacts=[],
            violations=[
                Violation(RULE_BYTES, "claude-code", "big.md", 5_500, 5_000, path)
            ],
            report="current",
        )

        with patch(
            "llm_prompts.size_guard.check_source", side_effect=[predicted, current]
        ):
            result = plugin.on_hook(
                "PreToolUse",
                tool_name="Edit",
                parameters={
                    "path": str(path),
                    "old_string": "old long text",
                    "new_string": "short",
                },
            )

        assert result is None

    def test_edit_leaving_measurement_unchanged_is_allowed(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        root = tmp_path / "size-root"
        for target in CHECKED_TARGETS:
            _write(root / target / "vars.json", "{}")
        padding = "x" * (FINALS[RULE_BYTES] + 50)
        path = _write(root / "shared" / "rules" / "big.md", "MARKER1" + padding)

        with patch("llm_prompts.size_guard._own_root_dir", return_value=root):
            result = plugin.on_hook(
                "PreToolUse",
                tool_name="Edit",
                parameters={
                    "path": str(path),
                    "old_string": "MARKER1",
                    "new_string": "MARKER2",
                },
            )

        assert result is None

    def test_edit_with_absent_old_string_returns_none(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        path = _write(tmp_path / "shared" / "rules" / "file.md", "hello world")
        result = plugin.on_hook(
            "PreToolUse",
            tool_name="Edit",
            parameters={"path": str(path), "old_string": "missing", "new_string": "x"},
        )
        assert result is None

    def test_edit_with_duplicate_old_string_and_no_replace_all_returns_none(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        path = _write(tmp_path / "shared" / "rules" / "file.md", "dup dup")
        result = plugin.on_hook(
            "PreToolUse",
            tool_name="Edit",
            parameters={"path": str(path), "old_string": "dup", "new_string": "x"},
        )
        assert result is None

    def test_replace_in_file_is_not_gated(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        result = plugin.on_hook(
            "PreToolUse",
            tool_name="replace_in_file",
            parameters={"path": str(tmp_path / "file.md"), "diff": "..."},
        )
        assert result is None

    def test_path_outside_any_prompts_root_returns_none(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        path = tmp_path / "random" / "rules" / "notes.md"
        result = plugin.on_hook(
            "PreToolUse",
            tool_name="Write",
            parameters={"path": str(path), "content": "hello"},
        )
        assert result is None

    def test_check_source_raising_fails_open(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        with patch(
            "llm_prompts.size_guard.check_source", side_effect=RuntimeError("boom")
        ):
            result = plugin.on_hook(
                "PreToolUse",
                tool_name="Write",
                parameters={
                    "path": str(tmp_path / "shared" / "rules" / "x.md"),
                    "content": "hello",
                },
            )
        assert result is None

    def test_no_stamp_or_pending_file_created(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        stamp = plugin._debouncer._stamp
        pending = plugin._debouncer._pending
        passing = CheckResult(passed=True, artifacts=[], violations=[], report="ok")

        with patch("llm_prompts.size_guard.check_source", return_value=passing):
            plugin.on_hook(
                "PreToolUse",
                tool_name="Write",
                parameters={
                    "path": str(tmp_path / "shared" / "rules" / "x.md"),
                    "content": "hello",
                },
            )

        assert not stamp.exists()
        assert not pending.exists()

    def test_non_md_file_is_not_gated_without_reading_or_measuring(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        path = tmp_path / "shared" / "rules" / "script.py"
        with patch("llm_prompts.size_guard.check_source") as mock_check:
            result = plugin.on_hook(
                "PreToolUse",
                tool_name="Write",
                parameters={"path": str(path), "content": "print('hi')"},
            )
        assert result is None
        mock_check.assert_not_called()

    def test_md_file_outside_gated_dirs_is_not_measured(
        self, plugin: AutoReinstallPlugin, tmp_path: Path
    ) -> None:
        path = tmp_path / "docs" / "notes.md"
        with patch("llm_prompts.size_guard.check_source") as mock_check:
            result = plugin.on_hook(
                "PreToolUse",
                tool_name="Write",
                parameters={"path": str(path), "content": "hello"},
            )
        assert result is None
        mock_check.assert_not_called()

    @pytest.mark.parametrize(
        "path",
        [
            Path("root/shared/rules/a.md"),
            Path("root/claude-code/rules/a.md"),
            Path("root/shared/workflows/a.md"),
            Path("root/claude-code/workflows/a.md"),
            Path("root/shared/skills/demo/SKILL.md"),
            Path("root/claude-code/skills/demo/SKILL.md"),
            Path("root/claude-code/agents/a.md"),
        ],
    )
    def test_shape_filter_accepts_every_gated_shape(self, path: Path) -> None:
        assert _looks_like_prompt_source(path)

    @pytest.mark.parametrize(
        "path",
        [
            Path("shared/rules/helper.py"),
            Path("docs/notes.md"),
            Path("README.md"),
            Path("shared/rules.md"),
        ],
    )
    def test_shape_filter_rejects_non_gated_shapes(self, path: Path) -> None:
        assert not _looks_like_prompt_source(path)


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


class TestSourcePathWatching:
    """Tests that source prompt dirs are watched, not just installed manifest paths."""

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.install._discover_overlay_paths", return_value=[])
    @patch("llm_prompts.hooks.read_manifest", return_value={})
    def test_rule_source_edit_triggers_reinstall(
        self,
        mock_manifest: MagicMock,
        mock_overlays: MagicMock,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        source_dir = tmp_path / "prompts"
        rule_file = source_dir / "shared" / "rules" / "coding.md"
        rule_file.parent.mkdir(parents=True)
        rule_file.write_text("# Coding guidelines")

        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        with patch("llm_prompts.hooks.files", return_value=tmp_path):
            result = plugin.on_hook(
                "PostToolUse",
                tool_name="Edit",
                parameters={"file_path": str(rule_file)},
            )
        assert result is not None
        assert any("Auto-reinstalled" in note for note in result.notes)

    @patch("llm_prompts.hooks.subprocess.run")
    @patch("llm_prompts.install._discover_overlay_paths", return_value=[])
    @patch("llm_prompts.hooks.read_manifest", return_value={})
    def test_nested_skill_source_edit_triggers_reinstall(
        self,
        mock_manifest: MagicMock,
        mock_overlays: MagicMock,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A skill source, nested two levels below the rules dir, is still watched."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        source_dir = tmp_path / "prompts"
        skill_file = source_dir / "shared" / "skills" / "example-skill" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("# Example skill")

        plugin = AutoReinstallPlugin()
        plugin._debouncer = _ReinstallDebouncer(tmp_path / "stamp")
        with patch("llm_prompts.hooks.files", return_value=tmp_path):
            result = plugin.on_hook(
                "PostToolUse",
                tool_name="Edit",
                parameters={"file_path": str(skill_file)},
            )
        assert result is not None
        assert any("Auto-reinstalled" in note for note in result.notes)
