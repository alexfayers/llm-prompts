"""Cline-hooks plugin that auto-reinstalls when installed prompt files are edited."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from cline_hooks.core.plugin import HookResult, HooksPlugin, UserFacingNote

from .manifest import read_manifest
from .setup import _UPDATE_INSTRUCTION

logger = logging.getLogger("hooks.llm-prompts")

_WRITE_TOOLS = frozenset(
    {"replace_in_file", "write_to_file", "Edit", "Write", "MultiEdit"}
)
_GATED_EDIT_TOOLS = frozenset({"Write", "write_to_file", "Edit"})
_GATED_PARENT_DIRS = frozenset({"rules", "workflows", "skills", "agents"})
_UPDATE_CHECK_INTERVAL = 60 * 60
_DEBOUNCED_TASK_START_SOURCES = frozenset({"resume", "compact"})


def _looks_like_prompt_source(path: Path) -> bool:
    """Return True if `path` has the shape of a gated prompt source file.

    Args:
        path: Candidate file path.

    Returns:
        True if `path` is a ``.md`` file with a ``rules``, ``workflows``,
        ``skills``, or ``agents`` path component.
    """
    return path.suffix == ".md" and bool(_GATED_PARENT_DIRS & set(path.parts))


def _predicted_content(
    tool_name: object, parameters: dict[str, object], current_content: str
) -> str | None:
    """Reconstruct a Write/Edit call's post-edit content, or None if not reconstructable.

    Args:
        tool_name: The gated tool name (``Write``, ``write_to_file``, or ``Edit``).
        parameters: The tool call's raw input parameters.
        current_content: The file's content before this call.

    Returns:
        The predicted post-edit content, or None when the call cannot be
        reconstructed faithfully (missing fields, an absent ``old_string``, or
        an ambiguous ``old_string`` occurring more than once without
        ``replace_all``).
    """
    if tool_name in ("Write", "write_to_file"):
        content = parameters.get("content")
        return content if isinstance(content, str) else None

    old_string = parameters.get("old_string")
    new_string = parameters.get("new_string")
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return None
    count = current_content.count(old_string)
    if count == 0:
        return None
    if parameters.get("replace_all"):
        return current_content.replace(old_string, new_string)
    if count > 1:
        return None
    return current_content.replace(old_string, new_string, 1)


_BANNER_DIVIDER = "=" * 60
_BANNER_TITLE = r"""
 _ _                                                 _
 | | |_ __ ___        _ __  _ __ ___  _ __ ___  _ __ | |_ ___
 | | | '_ ` _ \ _____| '_ \| '__/ _ \| '_ ` _ \| '_ \| __/ __|
 | | | | | | | |_____| |_) | | | (_) | | | | | | |_) | |_\__ \
 |_|_|_| |_| |_|     | .__/|_|  \___/|_| |_| |_| .__/ \__|___/
                     |_|                       |_|
""".strip("\n")
_ANSI_COLOR = "\033[1;36m"  # bold cyan
_ANSI_RESET = "\033[0m"


def _format_user_text(stripped_message: str) -> str:
    """Wrap update text in a colored header/footer banner so it's unmissable.

    Args:
        stripped_message: Update text with the model-directive instruction
            already removed.

    Returns:
        The message framed with a banner header and footer.
    """
    return (
        "\n"
        f"{_ANSI_COLOR}{_BANNER_DIVIDER}\n"
        f"{_BANNER_TITLE}\n"
        f"{_BANNER_DIVIDER}{_ANSI_RESET}\n"
        "\n"
        f"{stripped_message}\n"
        "\n"
        f"{_ANSI_COLOR}{_BANNER_DIVIDER}{_ANSI_RESET}"
    )


class _ReinstallDebouncer:
    """Tracks the last reinstall time via a stamp file to debounce across process invocations."""

    def __init__(
        self,
        stamp_path: Path | None = None,
        interval_seconds: float = _UPDATE_CHECK_INTERVAL,
        stamp_name: str = ".llm-prompts-update-check-stamp",
    ) -> None:
        if stamp_path is None:
            from platformdirs import user_data_dir

            stamp_path = Path(user_data_dir("cline-hooks")) / stamp_name
        self._stamp = stamp_path
        self._interval_seconds = interval_seconds

    def should_run(self) -> bool:
        """Return True if enough time has passed since the last reinstall."""
        if not self._stamp.exists():
            return True
        try:
            last_run = float(self._stamp.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return True
        return (time.time() - last_run) >= self._interval_seconds

    def mark_run(self) -> None:
        """Record that a run just happened."""
        self._stamp.parent.mkdir(parents=True, exist_ok=True)
        self._stamp.write_text(str(time.time()), encoding="utf-8")


class AutoReinstallPlugin(HooksPlugin):
    """Auto-runs ``llm-prompts update`` when an installed prompt file is edited."""

    def __init__(self) -> None:
        self._source_dirs: list[Path] | None = None
        self._update_check_debouncer = _ReinstallDebouncer()

    def _get_source_dirs(self) -> list[Path]:
        """Return the source prompt dirs, discovered once per plugin instance."""
        if self._source_dirs is None:
            from .install import _discover_overlay_paths, prompts_dir

            self._source_dirs = [
                prompts_dir("llm_prompts").resolve(),
                *(path.resolve() for path in _discover_overlay_paths()),
            ]
        return self._source_dirs

    def _is_tracked_path(self, resolved: Path) -> bool:
        """Return True if the path is a manifest file or inside a source prompt dir."""
        for agent_entry in read_manifest().values():
            for file_str in agent_entry.get("files", []):
                try:
                    if Path(file_str).resolve() == resolved:
                        return True
                except (OSError, ValueError):
                    continue
        return any(resolved.is_relative_to(d) for d in self._get_source_dirs())

    # Update prompts/shared/rules/hooks-llm-prompts.md if this note's behavior changes.
    def _on_task_start(self, source: str, agent_type: str) -> HookResult | None:
        """Check for llm-prompts source updates and report any as session notes.

        Args:
            source: The TaskStart source (e.g. "", "resume", "compact"). A
                genuine fresh start always runs the check, bypassing the
                debounce that otherwise throttles resume/compact firings.
            agent_type: Non-empty when this TaskStart fired inside a subagent
                rather than the main session; the update check never runs
                for subagents regardless of source.
        """
        if agent_type:
            return None

        if (
            source in _DEBOUNCED_TASK_START_SOURCES
            and not self._update_check_debouncer.should_run()
        ):
            return None

        from .cli import _collect_update_messages

        try:
            messages = _collect_update_messages()
        except (Exception, SystemExit):
            logger.warning("Failed to check for llm-prompts updates")
            return None

        self._update_check_debouncer.mark_run()
        if not messages:
            return None
        stripped = "\n\n".join(
            message for message in messages if message != _UPDATE_INSTRUCTION
        )
        return HookResult(
            notes=[message for message in messages],
            user_notes=[UserFacingNote(user_text=_format_user_text(stripped))],
        )

    def on_hook(self, hook_name: str, **kwargs: object) -> HookResult | None:
        """Dispatch TaskStart update checks, the PreToolUse size gate, and PostToolUse auto-reinstalls.

        Args:
            hook_name: The hook event name.
            **kwargs: Hook-specific keyword arguments.

        Returns:
            A HookResult with notes, or None.
        """
        if hook_name == "TaskStart":
            return self._on_task_start(
                str(kwargs.get("source", "")), str(kwargs.get("agent_type", ""))
            )

        if hook_name == "PreToolUse":
            return self._gate_edit(kwargs)

        edited = self._edited_installed_file(hook_name, kwargs)
        return self._run_update(edited) if edited else None

    def _gate_edit(self, kwargs: dict[str, object]) -> HookResult | None:
        """Deny a Write/Edit that would newly breach or worsen a prompt-size threshold.

        `_looks_like_prompt_source` cannot reject anything `check_source`
        would have gated - every shape `size_guard` measures is a `.md` file
        under a `rules`/`workflows`/`skills`/`agents` directory - so it is
        safe to skip the file read and the `size_guard` import for anything
        else, without weakening what actually gets measured.

        Args:
            kwargs: The PreToolUse hook's keyword arguments.

        Returns:
            A blocking HookResult naming the worsened metric(s), or None to
            allow the call - including when the size guard cannot measure it.
        """
        if kwargs.get("tool_name") not in _GATED_EDIT_TOOLS:
            return None

        parameters = kwargs.get("parameters")
        if not isinstance(parameters, dict):
            return None

        path_str = parameters.get("path") or parameters.get("file_path")
        if not path_str:
            return None
        path = Path(str(path_str))

        if not _looks_like_prompt_source(path):
            return None

        try:
            current_content = path.read_text(encoding="utf-8") if path.exists() else ""
        except (OSError, UnicodeDecodeError):
            return None

        predicted_content = _predicted_content(
            kwargs.get("tool_name"), parameters, current_content
        )
        if predicted_content is None:
            return None

        from .size_guard import check_source, format_report

        try:
            predicted_result = check_source(path, predicted_content)
            if predicted_result.passed:
                return None
            current_result = check_source(path, current_content)
        except (Exception, SystemExit):
            logger.warning("Failed to measure prompt size for %s", path)
            return None

        current_actuals = {
            (v.metric, v.target, v.dest_name): v.actual
            for v in current_result.violations
        }
        worsened = [
            v
            for v in predicted_result.violations
            if (v.metric, v.target, v.dest_name) not in current_actuals
            or current_actuals[(v.metric, v.target, v.dest_name)] < v.actual
        ]
        if not worsened:
            return None

        return HookResult(
            block="Blocked: this edit would breach the prompt-size guard.\n"
            + format_report(worsened)
        )

    def _edited_installed_file(
        self, hook_name: str, kwargs: dict[str, object]
    ) -> Path | None:
        """Return the resolved path if this hook is a write to a file the manifest tracks."""
        if hook_name != "PostToolUse":
            return None

        if kwargs.get("tool_name") not in _WRITE_TOOLS:
            return None

        parameters = kwargs.get("parameters")
        if not isinstance(parameters, dict):
            return None

        path_str = parameters.get("path") or parameters.get("file_path")
        if not path_str:
            return None

        try:
            resolved = Path(str(path_str)).resolve()
        except (OSError, ValueError):
            return None

        if not self._is_tracked_path(resolved):
            return None

        logger.info("Installed prompt file edited: %s", resolved)
        return resolved

    # Update prompts/shared/rules/hooks-llm-prompts.md if this note's behavior changes.
    def _run_update(self, path: Path) -> HookResult:
        """Reinstall one edited prompt file, reporting the outcome as a hook note."""
        try:
            completed = subprocess.run(
                ["llm-prompts", "update", "--only", str(path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("Failed to run llm-prompts update")
            return HookResult(notes=["Failed to auto-reinstall prompt files"])

        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            logger.warning("Failed to run llm-prompts update: %s", stderr)
            note = "Failed to auto-reinstall prompt files"
            if stderr:
                note += f":\n{stderr}"
            return HookResult(notes=[note])

        return HookResult(notes=["Auto-reinstalled prompt files"])
