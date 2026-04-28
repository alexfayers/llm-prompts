"""Cline-hooks plugin that auto-reinstalls when installed prompt files are edited."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from .manifest import read_manifest

try:
    from cline_hooks.core.plugin import HookResult, HooksPlugin
except ImportError:
    raise  # noqa: TRY004

logger = logging.getLogger("hooks.llm-prompts")

_WRITE_TOOLS = frozenset({"replace_in_file", "write_to_file"})
_DEBOUNCE_SECONDS = 5.0


class _ReinstallDebouncer:
    """Tracks the last reinstall time via a stamp file to debounce across process invocations."""

    def __init__(self, stamp_path: Path | None = None) -> None:
        if stamp_path is None:
            from platformdirs import user_data_dir  # noqa: PLC0415

            stamp_path = (
                Path(user_data_dir("cline-hooks")) / ".llm-prompts-reinstall-stamp"
            )
        self._stamp = stamp_path

    def should_run(self) -> bool:
        """Return True if enough time has passed since the last reinstall."""
        if not self._stamp.exists():
            return True
        try:
            last_run = float(self._stamp.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return True
        return (time.time() - last_run) >= _DEBOUNCE_SECONDS

    def mark_run(self) -> None:
        """Record that a reinstall just happened."""
        self._stamp.parent.mkdir(parents=True, exist_ok=True)
        self._stamp.write_text(str(time.time()), encoding="utf-8")


class AutoReinstallPlugin(HooksPlugin):
    """Auto-runs ``llm-prompts update`` when an installed prompt file is edited."""

    def __init__(self) -> None:
        self._installed_paths: frozenset[Path] | None = None
        self._debouncer = _ReinstallDebouncer()

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

    def on_hook(self, hook_name: str, **kwargs: object) -> HookResult | None:
        """Handle PostToolUse events for write tools targeting installed files.

        Args:
            hook_name: The hook event name.
            **kwargs: Hook-specific keyword arguments.

        Returns:
            A HookResult with a reinstall note, or None.
        """
        if hook_name != "PostToolUse":
            return None

        tool_name = kwargs.get("tool_name")
        if tool_name not in _WRITE_TOOLS:
            return None

        parameters = kwargs.get("parameters")
        if not isinstance(parameters, dict):
            return None

        path_str = parameters.get("path")
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

        logger.info("Installed prompt file edited: %s", resolved)
        try:
            subprocess.run(
                ["llm-prompts", "update"],  # noqa: S603, S607
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("Failed to run llm-prompts update")
            return HookResult(notes=["Failed to auto-reinstall prompt files"])

        self._debouncer.mark_run()
        self._installed_paths = None
        return HookResult(notes=["Auto-reinstalled prompt files"])
