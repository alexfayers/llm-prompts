"""Shared anonymous telemetry helpers: opt-out, install id, sending, scrubbing."""

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
from pathlib import Path
from subprocess import DEVNULL, CalledProcessError, Popen
from typing import Any
from urllib.request import Request, urlopen

import truststore

from . import home

POSTHOG_URL = "https://eu.i.posthog.com/i/v0/e/"
POSTHOG_TOKEN = "phc_u9CarYTyF9mvobdXzSZ7bCv9DVNj8yF3JFzzD2j3ixgS"
OPT_OUT_ENV = ("DO_NOT_TRACK", "LLM_PROMPTS_NO_TELEMETRY", "CI")
OPT_STATE_MAX_AGE = 24 * 60 * 60
SEND_TIMEOUT_SECONDS = 3
_MAX_CAUSES = 3
_MESSAGE_TYPES = frozenset({"IncompleteRead", "JSONDecodeError", "CalledProcessError"})
_MAX_MESSAGE_LENGTH = 200
_MIN_IDENTITY_LENGTH = 3
_MIN_SECRET_LENGTH = 8
_REDACTED = "<redacted>"
_GENERIC_PATTERNS = (
    r"[A-Za-z][A-Za-z0-9+.-]*://\S+",  # URL
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",  # email address
    r"(?:~|[A-Za-z]:)?[\w.-]*(?:[/\\][^\s'\"]+)+",  # file path
    r"\d{1,3}(?:\.\d{1,3}){3}",  # IPv4 address
    r"(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}",  # IPv6 address
    r"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}",  # hostname
    r"[A-Za-z0-9+/=_-]{20,}|\d{6,}",  # long token or number
)
PACKAGES = ("llm_prompts", "mcp_memory")
_ROOT = Path(__file__).parent.parent


def is_set(name: str) -> bool:
    """Return whether an environment variable is set to something other than empty or 0."""
    return os.environ.get(name, "0") not in ("", "0")


def read_config() -> dict[str, Any]:
    """Return the parsed llm-prompts config file, or an empty dict when it does not exist."""
    path = home.config_dir() / "config.toml"
    if not path.exists():
        return {}
    config: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    return config


def enabled() -> bool:
    """Return whether no opt-out env var, CI or config setting is set."""
    if any(is_set(n) for n in OPT_OUT_ENV):
        return False
    try:
        settings = read_config().get("telemetry", {})
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return isinstance(settings, dict) and settings.get("enabled", True) is True


def _state_path() -> Path:
    """Return the path of the telemetry state file."""
    return home.config_dir() / "telemetry.json"


def read_state() -> dict[str, Any]:
    """Return the telemetry state file, or an empty dict when it is missing or invalid."""
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def update_state(**fields: Any) -> None:
    """Merge fields into the telemetry state file, keeping the rest."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
    scratch.write_text(json.dumps({**read_state(), **fields}), encoding="utf-8")
    scratch.replace(path)


def install_id() -> str | None:
    """Return the random install id, or None before the first-run notice created it."""
    value = read_state().get("install_id")
    return value if isinstance(value, str) and value else None


def save_opt_state() -> bool:
    """Record whether this process's environment and config opt out, and when.

    Returns:
        Whether telemetry is enabled.
    """
    opted_in = enabled()
    update_state(opted_out=not opted_in, at=time.time())
    return opted_in


def may_send(max_age: float = OPT_STATE_MAX_AGE) -> bool:
    """Return whether the last opt-out record is under `max_age` seconds old and not opted out."""
    state = read_state()
    at = state.get("at")
    if not isinstance(at, int | float) or state.get("opted_out") is not False:
        return False
    return 0 <= time.time() - at < max_age


def post(body: str) -> bool:
    """POST a capture body to PostHog, returning whether it succeeded."""
    request = Request(POSTHOG_URL, body.encode(), {"Content-Type": "application/json"})
    try:
        with urlopen(
            request,
            timeout=SEND_TIMEOUT_SECONDS,
            context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        ):
            return True
    except Exception as error:
        if is_set("LLM_PROMPTS_TELEMETRY_DEBUG"):
            print(f"telemetry error: {error}", file=sys.stderr)
        return False


def send(
    event: dict[str, Any],
    install_id: str,
    module: str = __name__,
    resolve: Callable[[str], str] = str,
) -> None:
    """Post an event from a detached process, or inline when debugging.

    Args:
        event: The PostHog event without `api_key` and `distinct_id`.
        install_id: The random install id used as `distinct_id`.
        module: The module whose `__main__` delivers the body in the detached process.
        resolve: Rewrites the body before an inline debug post.
    """
    body = json.dumps({**event, "api_key": POSTHOG_TOKEN, "distinct_id": install_id})
    if is_set("LLM_PROMPTS_TELEMETRY_DEBUG"):
        body = resolve(body)
        print(
            f"telemetry payload: {body}\ntelemetry sent: {post(body)}", file=sys.stderr
        )
        return
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLM_PROMPTS_")}
    cmd = [sys.executable, "-m", module, body]
    Popen(cmd, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True, env=env)


def reportable(exc: BaseException) -> bool:
    """Return whether an exception is a crash rather than an exit or interrupt."""
    return not isinstance(exc, SystemExit | KeyboardInterrupt)


def causes(exc: BaseException) -> Iterator[BaseException]:
    """Yield up to `_MAX_CAUSES` exceptions that led to `exc`, nearest first."""
    for _ in range(_MAX_CAUSES):
        cause = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
        if cause is None:
            return
        yield cause
        exc = cause


def _strings(node: Any) -> Iterator[str]:
    """Yield every string value in a nested config."""
    if isinstance(node, dict):
        node = list(node.values())
    if isinstance(node, list):
        yield from (text for child in node for text in _strings(child))
    elif isinstance(node, str):
        yield node


def scrub(message: str, config: dict[str, Any]) -> str:
    """Redact this machine's identifying values, then generic patterns, and cap the length."""
    home_dir = Path.home()
    own = [str(home_dir), str(Path.cwd()), home_dir.name, platform.node()]
    own.append(str(_ROOT))
    own += [os.environ.get(n, "") for n in ("USER", "LOGNAME", "USERNAME")]
    secrets = [*os.environ.values(), *_strings(config)]
    known = {v for v in own if len(v) >= _MIN_IDENTITY_LENGTH}
    known |= {v for v in secrets if len(v) >= _MIN_SECRET_LENGTH}
    pattern = "|".join(map(re.escape, sorted(known, key=len, reverse=True)))
    message = re.sub(pattern, _REDACTED, message)
    return re.sub("|".join(_GENERIC_PATTERNS), _REDACTED, message)[:_MAX_MESSAGE_LENGTH]


def _package_path(filename: str, package: str) -> str:
    """Return a file's path starting at its package directory."""
    parts = Path(filename).parts
    if package not in parts:
        return Path(filename).name
    return Path(*parts[len(parts) - 1 - parts[::-1].index(package) :]).as_posix()


def exception_item(exc: BaseException, config: dict[str, Any]) -> dict[str, Any]:
    """Return an exception's type, scrubbed message if its type allows one, and package frames."""
    frames = [
        {
            "filename": _package_path(frame.f_code.co_filename, package),
            "module": frame.f_globals.get("__name__"),
            "function": frame.f_code.co_name,
            "lineno": lineno,
        }
        for frame, lineno in traceback.walk_tb(exc.__traceback__)
        if (package := str(frame.f_globals.get("__name__")).split(".")[0]) in PACKAGES
    ]
    item: dict[str, Any] = {"type": type(exc).__name__}
    if item["type"] in _MESSAGE_TYPES:
        sent = str(exc)
        if isinstance(exc, CalledProcessError):
            sent = f"Command returned non-zero exit status {exc.returncode}."
        item["value"] = scrub(sent, config)
    return {**item, "stacktrace": {"frames": frames}}


def exception_items(exc: BaseException, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return `exception_item` for `exc` and the exceptions that caused it."""
    return [exception_item(e, config) for e in (exc, *causes(exc))]


if __name__ == "__main__":
    post(sys.argv[1])
