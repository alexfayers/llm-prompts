"""Anonymous, opt-out usage telemetry for every command."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from types import TracebackType
from typing import Any

from . import telemetry_core
from .console import log
from .exit_reason import STOPPED_REASONS, ExitReason
from .home import is_rooted
from .manifest import read_manifest
from .setup import read_config

RESUME_ENV = "LLM_PROMPTS_TELEMETRY_RESUME"
_EXCEPTION_CONTEXT = (
    *("command", "run_id", "flags", "agents", "outcome", "duration_s"),
    *("os", "python", "schema"),
)
_SERVICES = {"llm_prompts.mcp._post": "mcp", "llm_prompts.github_api.request": "github"}
_NOTICE = (
    "llm-prompts sends anonymous usage telemetry after each command. "
    "Nothing is sent on this run. To opt out, set DO_NOT_TRACK=1 or "
    "LLM_PROMPTS_NO_TELEMETRY=1, or add `[telemetry]` with `enabled = false` to config.toml. "
    "See the README for what is sent."
)

_SESSION_ROLES = ("main", "reader", "writer")
_MODEL_TIERS = ("opus", "sonnet", "haiku")
_FRONTENDS = ("claude-code", "codex", "kiro", "pi", "antigravity")
_SESSION_START_SOURCES = {"": "fresh", "resume": "resume", "compact": "compact"}


SESSION_START_ENV = "LLM_PROMPTS_SESSION_START_MS"
_WAITS = {
    "inference": "inferenceMs",
    "command_wait": "commandMs",
    "user_wait": "userMs",
}


def _send_workflow(event: str, properties: dict[str, Any]) -> None:
    """Send ``event`` with ``properties``, the tool versions and platform fields, unless telemetry is off."""
    install_id = telemetry_core.active_install_id()
    if install_id is None:
        return
    versions = telemetry_core.versions(read_config())
    properties |= {name.replace("-", "_"): v for name, v in versions.items()}
    properties |= telemetry_core.context(2)
    telemetry_core.send({"event": event, "properties": properties}, install_id)


def _role_and_tier(role: str, model: str) -> dict[str, str]:
    """Return the fixed role and model tier codes for a session's role and model."""
    return {
        "role": role if role in _SESSION_ROLES else "other",
        "model_tier": next((t for t in _MODEL_TIERS if t in model), "other"),
    }


def send_session(stats: dict[str, Any]) -> None:
    """Send one pi session's numbers, its role and model tier, or its opened PR, unless telemetry is off.

    Args:
        stats: The session's role, model and totals, as the session-telemetry pi extension sends them, or ``{"event": "pr_opened"}``.
    """
    if stats.get("event") == "pr_opened":
        send_pr_opened()
        return
    calls = int(stats["calls"])
    cost = float(stats["cost"])
    context = int(stats["context"])
    wall_ms = float(stats["wallMs"])
    waits = {name: float(stats.get(key, 0)) for name, key in _WAITS.items()}
    _send_workflow(
        "pi_session",
        {
            **_role_and_tier(stats["role"], str(stats["model"])),
            "calls": calls,
            "cost": round(cost, 4),
            "cost_per_call": round(cost / calls, 4) if calls else None,
            "context_avg": round(context / calls) if calls else None,
            "context_peak": int(stats["peak"]),
            "cache_read_share": round(int(stats["cacheRead"]) / context, 3)
            if context
            else None,
            "compactions": int(stats["compactions"]),
            "wall_s": round(wall_ms / 1000, 1),
            **{f"{name}_s": round(ms / 1000, 1) for name, ms in waits.items()},
            **{
                f"{name}_share": round(ms / wall_ms, 3) if wall_ms else None
                for name, ms in waits.items()
            },
        },
    )


def send_pr_opened() -> None:
    """Send a `pr_opened` event with the time since the pi session started, its role and model tier."""
    started = os.environ.get(SESSION_START_ENV, "")
    _send_workflow(
        "pr_opened",
        {
            **_role_and_tier(
                os.environ.get("PI_CONTEXT_ROLE", "main"),
                os.environ.get("PI_MODEL", ""),
            ),
            "time_to_pr_s": round(time.time() - int(started) / 1000)
            if started.isdigit()
            else None,
        },
    )


def send_pr_review(*, rounds: int, clean: bool, deferred: int) -> None:
    """Send a `pr_review` event for a finished review loop.

    Args:
        rounds: The fix rounds the loop ran.
        clean: Whether the last review came back CLEAN.
        deferred: The findings the last review deferred.
    """
    _send_workflow(
        "pr_review",
        {
            "rounds": rounds,
            "end": "clean" if clean else "escalated",
            "deferred": deferred,
        },
    )


def send_session_start(frontend: str, source: str) -> None:
    """Send a `session_start` event with the fixed frontend and start source codes.

    Args:
        frontend: The running agent frontend's name.
        source: The TaskStart source ("", "resume" or "compact").
    """
    _send_workflow(
        "session_start",
        {
            "frontend": frontend if frontend in _FRONTENDS else "other",
            "source": _SESSION_START_SOURCES.get(source, "other"),
        },
    )


def _exception_event(
    exc: BaseException,
    properties: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build a PostHog exception event for `exc` and its causes."""
    event = telemetry_core.exception_event(
        exc,
        config,
        {
            **{k: properties[k] for k in _EXCEPTION_CONTEXT},
            "llm_prompts_commit": properties["to"]["llm-prompts"],
            "versions": properties["to"],
        },
    )
    calls = [
        f"{f['module']}.{f['function']}"
        for i in event["properties"]["$exception_list"]
        for f in i["stacktrace"]["frames"]
    ]
    event["properties"]["dependency"] = next(
        (_SERVICES[c] for c in calls if c in _SERVICES), None
    )
    return event


class Run(AbstractContextManager["Run"]):
    """One CLI command that reports a single event when it finishes."""

    def __init__(
        self, installed_version: Callable[[str], tuple[str | None, str | None]]
    ) -> None:
        """Start inactive until `begin` is called."""
        self.outcome = "ok"
        self.exit_reason: str | None = None
        self.auto_update: str | None = None
        self.check_failed_source: str | None = None
        self._installed_version = installed_version
        self._begun: dict[str, Any] | None = None

    @contextmanager
    def exit_outcome(self, outcome: str) -> Iterator[None]:
        """Name `outcome` for a failing exit raised inside the block.

        Args:
            outcome: The outcome to report when the block calls `sys.exit` non-zero.
        """
        try:
            yield
        except SystemExit as exit_:
            if exit_.code:
                self.outcome = outcome
            raise

    def _installed(self) -> dict[str, dict[str, str | None]]:
        """Return the installed commits and releases of every tracked package."""
        found = {name: self._installed_version(name) for name in telemetry_core.TRACKED}
        return {
            "commits": {name: commit for name, (commit, _) in found.items()},
            "releases": {name: release for name, (_, release) in found.items()},
        }

    def begin(self, command: str, flags: list[str], installs: bool = False) -> None:
        """Start tracking `command` unless opted out, rooted or no agents are installed.

        Takes over state from `RESUME_ENV`.

        Args:
            command: The command name.
            flags: The sorted flag names.
            installs: Whether the command can change installed versions, so their
                starting state is captured now.
        """
        handed_over = os.environ.pop(RESUME_ENV, "null")
        try:
            if not is_rooted() and read_manifest() and telemetry_core.save_opt_state():
                self._begun = {
                    "command": command,
                    "flags": flags,
                    "started_at": time.time(),
                    "run_id": uuid.uuid4().hex[:12],
                }
                self._begun.update(self._installed() if installs else {"commits": None})
                self.restore(json.loads(handed_over))
        except Exception as error:
            self._begun = None
            log("debug", f"Telemetry skipped: {error}")

    def hand_over(self) -> dict[str, Any] | None:
        """Stop reporting and return the state for the process that continues the command."""
        begun, self._begun = self._begun, None
        return begun

    def restore(self, state: dict[str, Any] | None) -> None:
        """Take over the start time and commits of the process that handed over."""
        if state and self._begun:
            self._begun.update({"releases": None, **state})

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Report the outcome of the finished command."""
        failed = exc is not None and not (isinstance(exc, SystemExit) and not exc.code)
        if failed and isinstance(exc, SystemExit):
            self.exit_reason = exc.reason if isinstance(exc, ExitReason) else "other"
        if failed and self.outcome == "ok":
            self.outcome = (
                "stopped"
                if self.exit_reason in STOPPED_REASONS
                else f"error:{type(exc).__name__}"
            )
        if self._begun and not isinstance(exc, KeyboardInterrupt):
            try:
                self._report(self._begun, exc)
            except Exception as error:
                log("debug", f"Telemetry skipped: {error}")

    def _report(self, begun: dict[str, Any], exc: BaseException | None) -> None:
        """Send the event, or show the first-run notice and send nothing."""
        install_id = telemetry_core.install_id()
        if install_id is None:
            print(_NOTICE, file=sys.stderr)
            telemetry_core.update_state(install_id=str(uuid.uuid4()))
            return
        config = read_config()
        tools = config.get("tools", [])

        properties = {
            "command": begun["command"],
            "run_id": begun["run_id"],
            "flags": begun["flags"],
            "from": telemetry_core.versions(
                config, begun["commits"], begun.get("releases")
            ),
            "to": telemetry_core.versions(config),
            "agents": sorted(read_manifest()),
            "overlay_count": sum(
                t.get("name") not in telemetry_core.TRACKED for t in tools
            ),
            "overlays": telemetry_core.overlay_versions(config),
            "outcome": self.outcome,
            "exit_reason": self.exit_reason,
            "auto_update": self.auto_update,
            "check_failed_source": self.check_failed_source,
            "duration_s": round(time.time() - begun["started_at"], 1),
            **telemetry_core.context(2),
        }
        telemetry_core.send(
            {"event": "command_run", "properties": properties}, install_id
        )
        if self.outcome.startswith("error:") and exc and telemetry_core.reportable(exc):
            telemetry_core.send(
                _exception_event(exc, properties, config),
                install_id,
            )
