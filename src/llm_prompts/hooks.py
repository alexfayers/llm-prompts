"""Cline-hooks plugin that auto-reinstalls when installed prompt files are edited."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any

from cline_hooks.core.plugin import HookResult, HooksPlugin, UserFacingNote

from . import network
from .manifest import read_manifest
from .setup import _CHANGELOG_PREFIX, _UPDATE_INSTRUCTION

logger = logging.getLogger("hooks.llm-prompts")

_WRITE_TOOLS = frozenset(
    {"replace_in_file", "write_to_file", "Edit", "Write", "MultiEdit"}
)
_GATED_EDIT_TOOLS = frozenset({"Write", "write_to_file", "Edit"})
_GATED_PARENT_DIRS = frozenset({"rules", "workflows", "skills", "agents"})
_UPDATE_CHECK_INTERVAL = 2 * 60 * 60
_SHOWN_SESSIONS_KEPT = 50
_FAILED_CHECK_RETRY_SECONDS = 10 * 60
_LOCK_WAIT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.05
_DEBOUNCED_TASK_START_SOURCES = frozenset({"resume", "compact"})
_AUTO_UPDATE_STARTED = (
    "llm-prompts is updating in the background. "
    "Reload once it finishes to use the new version."
)
_HEADLESS_ENTRYPOINTS = frozenset({"sdk-cli", "sdk-ts", "sdk-py"})
_REFRESH = (
    "import sys; from llm_prompts.hooks import refresh_update_check; "
    "refresh_update_check(*sys.argv[1:])"
)


def _is_headless() -> bool:
    """Return True when the session is headless or has opted out of update checks."""
    return (
        os.environ.get("CLAUDE_CODE_ENTRYPOINT") in _HEADLESS_ENTRYPOINTS
        or os.environ.get("LLM_PROMPTS_NO_UPDATE_CHECK") == "1"
    )


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
_UPDATE_LIST_HEADER = re.compile(r"(\[[^\]]+\] update available(?: \(.+\))?):")
_ANSI_COLOR = "\033[1;36m"  # bold cyan
_ANSI_RESET = "\033[0m"


def _shorten_for_user(message: str) -> str:
    """Keep an update message's header and changelog link, dropping its listed changes.

    Args:
        message: A single update message as built by ``_format_update_message``.

    Returns:
        The header and any changelog link line, or ``message`` unchanged when it lists nothing.
    """
    header, *rest = message.split("\n")
    if not (match := _UPDATE_LIST_HEADER.fullmatch(header)):
        return message
    links = rest[:1] if rest and rest[0].startswith(_CHANGELOG_PREFIX) else []
    return "\n".join([match[1], *links])


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
        self._notice_cache = stamp_path.with_name(stamp_path.name + ".notice")
        self._lock = stamp_path.with_name(stamp_path.name + ".lock")
        self._refresh_lock = stamp_path.with_name(stamp_path.name + ".refresh.lock")
        self._shown = stamp_path.with_name(stamp_path.name + ".shown")
        self._interval_seconds = interval_seconds

    def was_shown(self, task_id: str, messages: list[str]) -> bool:
        """Whether this session was already shown these update messages."""
        try:
            shown = json.loads(self._shown.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(shown, dict) and shown.get(task_id) == messages

    def record_shown(self, task_id: str, messages: list[str]) -> None:
        """Record the update messages this session was shown, keeping recent sessions only."""
        try:
            shown = json.loads(self._shown.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            shown = {}
        if not isinstance(shown, dict):
            shown = {}
        shown.pop(task_id, None)
        shown[task_id] = messages
        recent = dict(list(shown.items())[-_SHOWN_SESSIONS_KEPT:])
        self._shown.parent.mkdir(parents=True, exist_ok=True)
        self._shown.write_text(json.dumps(recent), encoding="utf-8")

    def should_run(self) -> bool:
        """Return True if enough time has passed since the last run."""
        if not self._stamp.exists():
            return True
        try:
            last_run = float(self._stamp.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return True
        return (time.time() - last_run) >= self._interval_seconds

    def moved(self, fingerprint: str) -> bool:
        """Return True if the installed versions moved since the cached notice."""
        cached: str = self._cache().get("fingerprint", "")
        return cached != fingerprint

    def mark_run(self, failed: bool = False) -> None:
        """Record that a run just happened, due again after ``_FAILED_CHECK_RETRY_SECONDS`` when it failed."""
        retry_offset = (
            self._interval_seconds - _FAILED_CHECK_RETRY_SECONDS if failed else 0
        )
        self._stamp.parent.mkdir(parents=True, exist_ok=True)
        self._stamp.write_text(str(time.time() - retry_offset), encoding="utf-8")

    def single_flight(self) -> AbstractContextManager[bool]:
        """Yield True once this process holds the cross-process check lock, False if it stays taken."""
        return _flock(self._lock, _LOCK_WAIT_SECONDS)

    def refreshing(self) -> AbstractContextManager[bool]:
        """Yield True while this process holds the background refresh lock, False if another refresh holds it."""
        return _flock(self._refresh_lock, 0)

    def refresh_in_background(self, fetch: bool) -> None:
        """Start ``refresh_update_check`` for this stamp in a detached process."""
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _REFRESH,
                str(self._stamp),
                "remote" if fetch else "local",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def store_notice(self, messages: list[str], fingerprint: str = "") -> None:
        """Cache the update messages with the installed-version fingerprint they were checked at."""
        from .cli import UpdateCheckFailure

        failures = [m for m in messages if isinstance(m, UpdateCheckFailure)]
        self._notice_cache.write_text(
            json.dumps(
                {"fingerprint": fingerprint, "messages": messages, "failures": failures}
            ),
            encoding="utf-8",
        )

    def cached_notice(self, fingerprint: str = "") -> list[str]:
        """Return the update messages cached at these installed versions."""
        cache = self._cache()
        from .cli import UpdateCheckFailure

        if cache.get("fingerprint", "") != fingerprint:
            return []
        failures = set(cache.get("failures", []))
        return [
            UpdateCheckFailure(m) if m in failures else m
            for m in cache.get("messages", [])
        ]

    def _cache(self) -> dict[str, Any]:
        """Return the cached notice record, or an empty one when absent or unreadable."""
        try:
            cache = json.loads(self._notice_cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return cache if isinstance(cache, dict) else {}


@contextmanager
def _flock(path: Path, wait_seconds: float) -> Iterator[bool]:
    """Yield True once this process holds the lock file at ``path``, False if it stays taken for ``wait_seconds``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock_file:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(_LOCK_POLL_SECONDS)
            else:
                yield True
                return


def refresh_update_check(stamp: str, refs: str = "remote") -> None:
    """Check for llm-prompts updates, cache the notice and start the automatic update when updates exist.

    Args:
        stamp: The update-check stamp path of the session that started this refresh.
        refs: ``remote`` to fetch, or ``local`` to rebuild the notice from the refs already fetched.
    """
    from . import telemetry, telemetry_core
    from .cli import (
        UpdateCheckFailure,
        _collect_update_messages,
        _get_installed_version,
        _installed_fingerprint,
    )

    debouncer = _ReinstallDebouncer(Path(stamp))
    with (
        debouncer.refreshing() as alone,
        telemetry.Run(_get_installed_version) as run,
    ):
        if not alone:
            return
        try:
            fingerprint = _installed_fingerprint()
            due = (
                debouncer.should_run()
                if refs == "remote"
                else debouncer.moved(fingerprint)
            )
            if not due:
                return
            if telemetry_core.install_id():
                run.begin("startup-check", [] if refs == "remote" else ["--local"])
            if refs == "remote":
                with network.fail_fast():
                    messages = _collect_update_messages()
            else:
                previous = debouncer._cache().get("fingerprint", "")
                messages = _collect_update_messages(
                    previous=(previous, debouncer.cached_notice(previous))
                )
        except (Exception, SystemExit):
            logger.warning("Failed to check for llm-prompts updates")
            if refs == "remote":
                debouncer.mark_run(failed=True)
            return
        with debouncer.single_flight() as holds_lock:
            if not holds_lock:
                return
            failed = any(isinstance(m, UpdateCheckFailure) for m in messages)
            if refs == "remote":
                debouncer.mark_run(failed)
            if not failed:
                run.auto_update = (
                    _start_auto_update(fingerprint) if messages else "no-update"
                )
                if run.auto_update == "started":
                    messages = [*messages, _AUTO_UPDATE_STARTED]
            debouncer.store_notice(messages, fingerprint)


def _start_auto_update(fingerprint: str) -> str:
    """Start the automatic update, and return ``started`` or what blocked it, logging instead of raising."""
    from . import auto_update

    try:
        return auto_update.start(fingerprint)
    except (Exception, SystemExit):
        logger.warning("Failed to start the automatic llm-prompts update")
        return "error"


def _auto_update_failure(fingerprint: str) -> str | None:
    """Return why the last automatic update failed, logging instead of raising."""
    from . import auto_update

    try:
        return auto_update.failure(fingerprint)
    except (Exception, SystemExit):
        logger.warning("Failed to read the automatic llm-prompts update result")
        return None


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
    def _on_task_start(
        self, source: str, agent_type: str, task_id: str = ""
    ) -> HookResult | None:
        """Check for llm-prompts source updates and report any as session notes.

        Args:
            source: The TaskStart source (e.g. "", "resume", "compact"). Within
                the check interval a fresh start re-emits the cached notice
                while resume/compact emit a cached notice once per session.
            agent_type: Non-empty when this TaskStart fired inside a subagent
                rather than the main session; the update check never runs
                for subagents regardless of source.
            task_id: The session id that keys which notice it was shown.
        """
        if agent_type or _is_headless():
            return None

        from . import telemetry
        from .cli import _get_installed_version, _installed_fingerprint

        try:
            fingerprint = _installed_fingerprint()
        except (Exception, SystemExit):
            logger.warning("Failed to read installed llm-prompts versions")
            return None
        with (
            telemetry.Run(_get_installed_version) as run,
            self._update_check_debouncer.single_flight() as holds_lock,
        ):
            fetch = self._update_check_debouncer.should_run()
            if holds_lock and (
                fetch or self._update_check_debouncer.moved(fingerprint)
            ):
                self._update_check_debouncer.refresh_in_background(fetch)
                messages = self._update_check_debouncer.cached_notice(fingerprint)
                self._update_check_debouncer.record_shown(task_id, messages)
            elif source in _DEBOUNCED_TASK_START_SOURCES:
                messages = []
                if (
                    notice := self._update_check_debouncer.cached_notice(fingerprint)
                ) and not self._update_check_debouncer.was_shown(task_id, notice):
                    self._update_check_debouncer.record_shown(task_id, notice)
                    messages = notice
            else:
                run.begin("startup-check", ["--cached"])
                messages = self._update_check_debouncer.cached_notice(fingerprint)
                self._update_check_debouncer.record_shown(task_id, messages)

        if reason := _auto_update_failure(fingerprint):
            messages = [
                *(m for m in messages if m != _AUTO_UPDATE_STARTED),
                f"The automatic update failed: {reason}\nRun `llm-prompts update` to see why.",
            ]
        if not messages:
            return None
        stripped = "\n\n".join(
            _shorten_for_user(message)
            for message in messages
            if message != _UPDATE_INSTRUCTION
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
                str(kwargs.get("source", "")),
                str(kwargs.get("agent_type", "")),
                str(kwargs.get("task_id", "")),
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
            from .auto_update import UPDATE_RUNNING

            if UPDATE_RUNNING in stderr:
                return HookResult(
                    notes=[
                        "Skipped auto-reinstall: a running llm-prompts update installs the edit"
                    ]
                )
            logger.warning("Failed to run llm-prompts update: %s", stderr)
            note = "Failed to auto-reinstall prompt files"
            if stderr:
                note += f":\n{stderr}"
            return HookResult(notes=[note])

        return HookResult(notes=["Auto-reinstalled prompt files"])
