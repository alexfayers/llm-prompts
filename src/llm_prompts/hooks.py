"""Cline-hooks plugin that auto-reinstalls when installed prompt files are edited."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from .manifest import read_manifest
from .setup import _UPDATE_INSTRUCTION

try:
    from cline_hooks.core.plugin import HookResult, HooksPlugin, UserFacingNote
except ImportError:
    raise  # noqa: TRY004

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
            from platformdirs import user_data_dir  # noqa: PLC0415

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
        """Record that a reinstall just happened."""
        self._stamp.parent.mkdir(parents=True, exist_ok=True)
        self._stamp.write_text(str(time.time()), encoding="utf-8")


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
        """Load and cache resolved paths of all installed files from the manifest."""
        if self._installed_paths is None:
            paths: set[Path] = set()
            for agent_entry in read_manifest().values():
                for file_str in agent_entry.get("files", []):
                    try:
                        paths.add(Path(file_str).resolve())
                    except (OSError, ValueError):
                        continue
            self._installed_paths = frozenset(paths)
        return self._installed_paths

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

        from .cli import _collect_update_messages  # noqa: PLC0415

        try:
            messages = _collect_update_messages()
        except (Exception, SystemExit):
            logger.warning("Failed to check for llm-prompts updates")
            return None

        self._update_check_debouncer.mark_run()
        if not messages:
            return None
        return HookResult(
            notes=[message for message in messages],
            user_notes=[
                UserFacingNote(
                    user_text=_format_user_text(_strip_update_instruction(message)),
                )
                for message in messages
            ],
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

        if hook_name != "PostToolUse":
            return None

        tool_name = kwargs.get("tool_name")
        if tool_name not in _WRITE_TOOLS:
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

        if resolved not in self._get_installed_paths():
            return None

        if not self._debouncer.should_run():
            return None

        # Update prompts/shared/rules/hooks-llm-prompts.md if this note's behavior changes.
        logger.info("Installed prompt file edited: %s", resolved)
        try:
            completed = subprocess.run(
                ["llm-prompts", "update"],  # noqa: S603, S607
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("Failed to run llm-prompts update")
            return HookResult(notes=["Failed to auto-reinstall prompt files"])

        if completed.returncode != 0:
            logger.warning("Failed to run llm-prompts update")
            return HookResult(notes=["Failed to auto-reinstall prompt files"])

        self._debouncer.mark_run()
        self._installed_paths = None
        return HookResult(notes=["Auto-reinstalled prompt files"])
