"""Anonymous, opt-out usage telemetry for every command."""

from __future__ import annotations

import json
import os
import platform
import re
import ssl
import sys
import time
import tomllib
import traceback
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from subprocess import DEVNULL, Popen, SubprocessError, run
from types import TracebackType
from typing import Any
from urllib.request import Request, urlopen

import truststore

from . import home
from .install import log
from .manifest import read_manifest
from .setup import _expand, _is_local_path, read_config

POSTHOG_URL = "https://eu.i.posthog.com/i/v0/e/"
POSTHOG_TOKEN = "phc_u9CarYTyF9mvobdXzSZ7bCv9DVNj8yF3JFzzD2j3ixgS"
RESUME_ENV = "LLM_PROMPTS_TELEMETRY_RESUME"
_SEND_TIMEOUT_SECONDS = 3
_CHECKOUT_KEY = "checkout"
_INSTALLED_KEY = "installed"
_GITHUB_SOURCE = re.compile(r"^(git\+)?(https://|ssh://git@|git@)github\.com[/:]")
_PACKAGE = __name__.partition(".")[0]
_ROOT = Path(__file__).parent.parent
_TRACKED = ("llm-prompts", "cline-hooks", "mcp-memory")
_NOTICE = (
    "llm-prompts sends anonymous usage telemetry after each command. "
    "Nothing is sent on this run. To opt out, set DO_NOT_TRACK=1 or "
    "LLM_PROMPTS_NO_TELEMETRY=1, or add `[telemetry]` with `enabled = false` to config.toml. "
    "See the README for what is sent."
)


def _is_set(name: str) -> bool:
    """Return whether an environment variable is set to something other than empty or 0."""
    return os.environ.get(name, "0") not in ("", "0")


def _checkout_state(repo: str) -> dict[str, Any]:
    """Return the version entry of a local git checkout."""
    try:
        head = run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=_SEND_TIMEOUT_SECONDS,
        ).stdout.strip()
        status = run(
            ["git", "-C", repo, "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            timeout=_SEND_TIMEOUT_SECONDS,
        ).stdout
    except (OSError, ValueError, SubprocessError):
        return {"commit": None, "local": True, "dirty": None, "ahead": None}
    return {
        "commit": head,
        "local": True,
        "dirty": bool(status.strip()),
        "ahead": _commits_ahead(repo),
    }


def _commits_ahead(repo: str) -> int | None:
    """Return how many commits HEAD has over origin/main, or None if that cannot be counted."""
    try:
        counted = run(
            ["git", "-C", repo, "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=_SEND_TIMEOUT_SECONDS,
        ).stdout
        return int(counted)
    except (OSError, ValueError, SubprocessError):
        return None


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


def _remote(commit: str | None) -> dict[str, Any]:
    """Return the version entry of a source installed from git."""
    return {"commit": commit, "local": False, "dirty": False, "ahead": None}


def enabled() -> bool:
    """Return whether no opt-out env var, CI or config setting is set."""
    if any(_is_set(n) for n in ("DO_NOT_TRACK", "LLM_PROMPTS_NO_TELEMETRY", "CI")):
        return False
    try:
        settings = read_config().get("telemetry", {})
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return isinstance(settings, dict) and settings.get("enabled", True) is True


def post(body: str) -> bool:
    """POST a capture body to PostHog, returning whether it succeeded."""
    request = Request(POSTHOG_URL, body.encode(), {"Content-Type": "application/json"})
    try:
        with urlopen(
            request,
            timeout=_SEND_TIMEOUT_SECONDS,
            context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        ):
            return True
    except Exception as error:
        if _is_set("LLM_PROMPTS_TELEMETRY_DEBUG"):
            print(f"telemetry error: {error}", file=sys.stderr)
        return False


def send(event: dict[str, Any], install_id: str) -> None:
    """Post an event from a detached process, or inline when debugging."""
    body = json.dumps({**event, "api_key": POSTHOG_TOKEN, "distinct_id": install_id})
    if _is_set("LLM_PROMPTS_TELEMETRY_DEBUG"):
        body = _resolve_checkouts(body)
        print(
            f"telemetry payload: {body}\ntelemetry sent: {post(body)}", file=sys.stderr
        )
        return
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLM_PROMPTS_")}
    cmd = [sys.executable, "-m", __name__, body]
    Popen(cmd, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True, env=env)


def _reportable(exc: BaseException) -> bool:
    """Return whether an exception is a crash rather than an exit or interrupt."""
    return not isinstance(exc, SystemExit | KeyboardInterrupt)


def _exception_event(
    exc: BaseException, command: str, commit: dict[str, str]
) -> dict[str, Any]:
    """Build a PostHog exception event with the type and this package's frames only."""
    frames = [
        {
            "filename": (Path(frame.f_code.co_filename).relative_to(_ROOT)).as_posix(),
            "module": frame.f_globals.get("__name__"),
            "function": frame.f_code.co_name,
            "lineno": lineno,
        }
        for frame, lineno in traceback.walk_tb(exc.__traceback__)
        if str(frame.f_globals.get("__name__")).split(".")[0] == _PACKAGE
    ]
    item = {"type": type(exc).__name__, "stacktrace": {"frames": frames}}
    return {
        "event": "$exception",
        "properties": {
            "$exception_list": [item],
            "command": command,
            "llm_prompts_commit": commit,
            "$process_person_profile": False,
        },
    }


class Run(AbstractContextManager["Run"]):
    """One CLI command that reports a single event when it finishes."""

    def __init__(self, installed_commit: Callable[[str], str | None]) -> None:
        """Start inactive until `begin` is called."""
        self.outcome = "ok"
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
            if enabled():
                self._begun = {
                    "command": command,
                    "flags": flags,
                    "started_at": time.time(),
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
        if failed and self.outcome == "ok":
            self.outcome = f"error:{type(exc).__name__}"
        if self._begun:
            try:
                self._report(self._begun, exc)
            except Exception as error:
                log("debug", f"Telemetry skipped: {error}")

    def _report(self, begun: dict[str, Any], exc: BaseException | None) -> None:
        """Send the event, or show the first-run notice and send nothing."""
        path = home.config_dir() / "telemetry.json"
        try:
            install_id = json.loads(path.read_text(encoding="utf-8"))["install_id"]
        except (OSError, ValueError, KeyError, TypeError):
            print(_NOTICE, file=sys.stderr)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"install_id": str(uuid.uuid4())}), encoding="utf-8"
            )
            return
        tools = read_config().get("tools", [])
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
            "duration_s": round(time.time() - begun["started_at"], 1),
            "os": platform.system(),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "schema": 2,
            "$process_person_profile": False,
        }
        send({"event": "command_run", "properties": properties}, install_id)
        if self.outcome.startswith("error:") and exc and _reportable(exc):
            send(
                _exception_event(exc, begun["command"], commits(None)["llm-prompts"]),
                install_id,
            )


if __name__ == "__main__":
    deliver(sys.argv[1])
