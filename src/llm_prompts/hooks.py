"""Cline-hooks plugin that auto-reinstalls when installed prompt files are edited."""

from __future__ import annotations

import logging
import subprocess
import time
from importlib.resources import files
from pathlib import Path

from cline_hooks.core.plugin import HookResult, HooksPlugin, UserFacingNote

from .manifest import read_manifest
from .setup import _UPDATE_INSTRUCTION

logger = logging.getLogger("hooks.llm-prompts")

_WRITE_TOOLS = frozenset(
    {"replace_in_file", "write_to_file", "Edit", "Write", "MultiEdit"}
)
_DEBOUNCE_SECONDS = 5.0
_UPDATE_CHECK_INTERVAL = 60 * 60
_DEBOUNCED_TASK_START_SOURCES = frozenset({"resume", "compact"})


def _strip_update_instruction(message: str) -> str:
    """Return ``message`` without the trailing model-directive instruction.

    Strips ``_UPDATE_INSTRUCTION`` and the newline immediately preceding it
    when present, leaving the bare "update available" fallback (which carries
    no instruction) unchanged.

    Args:
        message: An update-availability message string.

    Returns:
        The message with the trailing instruction removed, or unchanged.
    """
    suffix = "\n" + _UPDATE_INSTRUCTION
    if message.endswith(suffix):
        return message[: -len(suffix)]
    return message


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
            already removed (see ``_strip_update_instruction``).

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
        interval_seconds: float = _DEBOUNCE_SECONDS,
        stamp_name: str = ".llm-prompts-reinstall-stamp",
    ) -> None:
        if stamp_path is None:
            from platformdirs import user_data_dir

            stamp_path = Path(user_data_dir("cline-hooks")) / stamp_name
        self._stamp = stamp_path
        self._pending = stamp_path.with_name(f"{stamp_path.name}.pending")
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
        """Record that a reinstall just happened, satisfying any pending request."""
        self._stamp.parent.mkdir(parents=True, exist_ok=True)
        self._stamp.write_text(str(time.time()), encoding="utf-8")
        self._pending.unlink(missing_ok=True)

    def mark_pending(self) -> None:
        """Record that a request was skipped and still needs a run."""
        self._pending.parent.mkdir(parents=True, exist_ok=True)
        self._pending.touch()

    def is_pending(self) -> bool:
        """Return True if a skipped request is still waiting for a run."""
        return self._pending.exists()


class AutoReinstallPlugin(HooksPlugin):
    """Auto-runs ``llm-prompts update`` when an installed prompt file is edited."""

    def __init__(self) -> None:
        self._installed_paths: frozenset[Path] | None = None
        self._debouncer = _ReinstallDebouncer()
        self._update_check_debouncer = _ReinstallDebouncer(
            interval_seconds=_UPDATE_CHECK_INTERVAL,
            stamp_name=".llm-prompts-update-check-stamp",
        )

    def _get_installed_paths(self) -> frozenset[Path]:
        """Load and cache resolved paths of all installed and source files."""
        if self._installed_paths is None:
            paths: set[Path] = set()
            for agent_entry in read_manifest().values():
                for file_str in agent_entry.get("files", []):
                    try:
                        paths.add(Path(file_str).resolve())
                    except (OSError, ValueError):
                        continue
            paths.update(self._get_source_paths())
            self._installed_paths = frozenset(paths)
        return self._installed_paths

    @staticmethod
    def _get_source_paths() -> set[Path]:
        """Return resolved paths of every file under the source prompt dirs.

        Rules and agent variants are rendered copies rather than symlinks, so
        editing their sources never resolves to a manifest path; walking the
        source trees directly catches those edits too. This must be
        recursive: skills live nested at ``prompts/*/skills/<name>/SKILL.md``,
        so a shallow glob would miss every skill.
        """
        from .install import _discover_overlay_paths

        dirs = [Path(str(files("llm_prompts") / "prompts")), *_discover_overlay_paths()]
        return {
            path.resolve()
            for prompts_dir in dirs
            if prompts_dir.is_dir()
            for path in prompts_dir.rglob("*")
            if path.is_file()
        }

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
            _strip_update_instruction(message) for message in messages
        )
        return HookResult(
            notes=[message for message in messages],
            user_notes=[UserFacingNote(user_text=_format_user_text(stripped))],
        )

    def on_hook(self, hook_name: str, **kwargs: object) -> HookResult | None:
        """Dispatch TaskStart update checks and PostToolUse auto-reinstalls.

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

        if not self._is_installed_file_edit(hook_name, kwargs):
            return self._flush_pending()

        if not self._debouncer.should_run():
            self._debouncer.mark_pending()
            return None

        return self._run_update()

    def _is_installed_file_edit(
        self, hook_name: str, kwargs: dict[str, object]
    ) -> bool:
        """Return True if this hook is a write to a file the manifest tracks."""
        if hook_name != "PostToolUse":
            return False

        if kwargs.get("tool_name") not in _WRITE_TOOLS:
            return False

        parameters = kwargs.get("parameters")
        if not isinstance(parameters, dict):
            return False

        path_str = parameters.get("path") or parameters.get("file_path")
        if not path_str:
            return False

        try:
            resolved = Path(str(path_str)).resolve()
        except (OSError, ValueError):
            return False

        if resolved not in self._get_installed_paths():
            return False

        logger.info("Installed prompt file edited: %s", resolved)
        return True

    def _flush_pending(self) -> HookResult | None:
        """Run a reinstall the debounce deferred, once the interval has elapsed."""
        if not self._debouncer.is_pending() or not self._debouncer.should_run():
            return None
        return self._run_update()

    # Update prompts/shared/rules/hooks-llm-prompts.md if this note's behavior changes.
    def _run_update(self) -> HookResult:
        """Reinstall every prompt file, reporting the outcome as a hook note."""
        try:
            completed = subprocess.run(
                ["llm-prompts", "update"],
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

        self._debouncer.mark_run()
        self._installed_paths = None
        return HookResult(notes=["Auto-reinstalled prompt files"])
