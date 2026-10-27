"""Anonymous, opt-out usage telemetry for every command."""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from subprocess import SubprocessError, run
from types import TracebackType
from typing import Any

from . import telemetry_core
from .exit_reason import ExitReason
from .install import log
from .manifest import read_manifest
from .setup import _expand, _is_local_path, read_config
from .telemetry_core import SEND_TIMEOUT_SECONDS, exception_items, post
from .telemetry_core import send as core_send

RESUME_ENV = "LLM_PROMPTS_TELEMETRY_RESUME"
_EXCEPTION_CONTEXT = (
    *("command", "run_id", "flags", "agents", "outcome", "duration_s"),
    *("os", "python", "schema"),
)
_CHECKOUT_KEY = "checkout"
_INSTALLED_KEY = "installed"
_GITHUB_SOURCE = re.compile(r"^(git\+)?(https://|ssh://git@|git@)github\.com[/:]")
_SERVICES = {"llm_prompts.mcp._post": "mcp", "llm_prompts.github_api.request": "github"}
_TRACKED = ("llm-prompts", "cline-hooks", "mcp-memory")
_NOTICE = (
    "llm-prompts sends anonymous usage telemetry after each command. "
    "Nothing is sent on this run. To opt out, set DO_NOT_TRACK=1 or "
    "LLM_PROMPTS_NO_TELEMETRY=1, or add `[telemetry]` with `enabled = false` to config.toml. "
    "See the README for what is sent."
)


def _git(repo: str, *args: str) -> str:
    """Return the output of a git command run in `repo`."""
    return run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=SEND_TIMEOUT_SECONDS,
    ).stdout


def _checkout_state(repo: str) -> dict[str, Any]:
    """Return the version entry of a local git checkout, naming only a commit on origin/main."""
    try:
        dirty = bool(_git(repo, "status", "--porcelain").strip())
    except (OSError, ValueError, SubprocessError):
        return _local_state(None, None, None)
    try:
        base = _git(repo, "merge-base", "HEAD", "origin/main").strip()
        ahead = int(_git(repo, "rev-list", "--count", f"{base}..HEAD"))
    except (OSError, ValueError, SubprocessError):
        return _local_state(None, dirty, None)
    return _local_state(base, dirty, ahead)


def _local_state(
    base: str | None, dirty: bool | None, ahead: int | None
) -> dict[str, Any]:
    """Return a local checkout's entry, which never names a commit missing from origin/main."""
    return {
        "commit": None,
        "base": base,
        "local": True,
        "dirty": dirty,
        "ahead": ahead,
    }


def _local(source: str) -> dict[str, str]:
    """Return a placeholder the detached sender replaces with the checkout state."""
    return {_CHECKOUT_KEY: str(_expand(source))}


def _installed(package: str) -> dict[str, str]:
    """Return a placeholder the detached sender replaces with the package's installed version."""
    return {_INSTALLED_KEY: package}


def _resolve_checkouts(body: str) -> str:
    """Replace every placeholder in a JSON body with its checkout or installed state."""
    from .cli import _get_installed_commit

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if _CHECKOUT_KEY in node:
                return _checkout_state(node[_CHECKOUT_KEY])
            if _INSTALLED_KEY in node:
                return _remote(_get_installed_commit(node[_INSTALLED_KEY]))
            return {k: resolve(v) for k, v in node.items()}
        return node

    return json.dumps(resolve(json.loads(body)))


def deliver(body: str) -> None:
    """Resolve local checkouts in a body and post it."""
    post(_resolve_checkouts(body))


def send(event: dict[str, Any], install_id: str) -> None:
    """Post an event from a detached process that resolves local checkouts first."""
    core_send(event, install_id, module=__name__, resolve=_resolve_checkouts)


def _remote(commit: str | None) -> dict[str, Any]:
    """Return the version entry of a source installed from git."""
    return {
        "commit": commit,
        "base": commit,
        "local": False,
        "dirty": False,
        "ahead": None,
    }


def _exception_event(
    exc: BaseException,
    properties: dict[str, Any],
    commit: dict[str, str],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build a PostHog exception event for `exc` and its causes."""
    items = exception_items(exc, config)
    calls = [
        f"{f['module']}.{f['function']}"
        for i in items
        for f in i["stacktrace"]["frames"]
    ]
    return {
        "event": "$exception",
        "properties": {
            "$exception_list": items,
            "dependency": next((_SERVICES[c] for c in calls if c in _SERVICES), None),
            **{k: properties[k] for k in _EXCEPTION_CONTEXT},
            "llm_prompts_commit": commit,
            "$process_person_profile": False,
        },
    }


class Run(AbstractContextManager["Run"]):
    """One CLI command that reports a single event when it finishes."""

    def __init__(self, installed_commit: Callable[[str], str | None]) -> None:
        """Start inactive until `begin` is called."""
        self.outcome = "ok"
        self.exit_reason: str | None = None
        self._installed_commit = installed_commit
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

    def _commits(self) -> dict[str, str | None]:
        """Return the installed commit of every tracked package."""
        return {name: self._installed_commit(name) for name in _TRACKED}

    def begin(self, command: str, flags: list[str], installs: bool = False) -> None:
        """Start tracking `command` unless opted out, taking over state from `RESUME_ENV`.

        Args:
            command: The command name.
            flags: The sorted flag names.
            installs: Whether the command can change installed versions, so their
                starting state is captured now.
        """
        handed_over = os.environ.pop(RESUME_ENV, "null")
        try:
            if telemetry_core.save_opt_state():
                self._begun = {
                    "command": command,
                    "flags": flags,
                    "started_at": time.time(),
                    "run_id": uuid.uuid4().hex[:12],
                }
                self._begun["commits"] = self._commits() if installs else None
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
            self._begun.update(state)

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
            self.outcome = f"error:{type(exc).__name__}"
        if self._begun:
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
        local = {
            t.get("name"): _local(str(t.get("source")))
            for t in tools
            if _is_local_path(str(t.get("source")))
        }

        def commits(found: dict[str, str | None] | None) -> dict[str, dict[str, Any]]:
            return {
                n: local.get(n)
                or (_remote(found.get(n)) if found is not None else _installed(n))
                for n in _TRACKED
            }

        properties = {
            "command": begun["command"],
            "run_id": begun["run_id"],
            "flags": begun["flags"],
            "from": commits(begun["commits"]),
            "to": commits(None),
            "agents": sorted(read_manifest()),
            "overlay_count": sum(t.get("name") not in _TRACKED for t in tools),
            "overlays": {
                n: local.get(n) or _installed(n)
                for t in tools
                if (n := t.get("name")) not in _TRACKED
                and _GITHUB_SOURCE.match(str(t.get("source")))
            },
            "outcome": self.outcome,
            "exit_reason": self.exit_reason,
            "duration_s": round(time.time() - begun["started_at"], 1),
            "os": platform.system(),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "schema": 2,
            "$process_person_profile": False,
        }
        send({"event": "command_run", "properties": properties}, install_id)
        if self.outcome.startswith("error:") and exc and telemetry_core.reportable(exc):
            send(
                _exception_event(exc, properties, commits(None)["llm-prompts"], config),
                install_id,
            )


if __name__ == "__main__":
    deliver(sys.argv[1])
