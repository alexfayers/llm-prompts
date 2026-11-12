"""Shared anonymous telemetry helpers: opt-out, install id, sending, scrubbing."""

from __future__ import annotations

import functools
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
from subprocess import DEVNULL, CalledProcessError, Popen, SubprocessError, run
from typing import Any
from urllib.request import Request, urlopen

import truststore

from . import home

POSTHOG_URL = "https://eu.i.posthog.com/i/v0/e/"
DEBUG_ENV = "LLM_PROMPTS_TELEMETRY_DEBUG"
POSTHOG_TOKEN = "phc_u9CarYTyF9mvobdXzSZ7bCv9DVNj8yF3JFzzD2j3ixgS"
OPT_OUT_ENV = ("DO_NOT_TRACK", "LLM_PROMPTS_NO_TELEMETRY", "CI")
OPT_STATE_MAX_AGE = 24 * 60 * 60
SEND_TIMEOUT_SECONDS = 3
_MAX_CAUSES = 3
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
PACKAGES = ("llm_prompts", "cline_hooks", "mcp_memory")
_MESSAGE_PACKAGES = ("llm_prompts", "cline_hooks")
_WITHHELD = "<message withheld>"
_ROOT = Path(__file__).parent.parent
TRACKED = ("llm-prompts", "cline-hooks", "mcp-memory")
_CHECKOUT_KEY = "checkout"
_INSTALLED_KEY = "installed"
_GITHUB_SOURCE = re.compile(r"^(git\+)?(https://|ssh://git@|git@)github\.com[/:]")


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


def active_install_id() -> str | None:
    """Return the install id when telemetry is on and the opt-out record is fresh, else None."""
    return install_id() if enabled() and may_send() else None


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
        if is_set(DEBUG_ENV):
            print(f"telemetry error: {error}", file=sys.stderr)
        return False


def _git(repo: str, *args: str) -> str:
    """Return the output of a git command run in `repo`."""
    return run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=SEND_TIMEOUT_SECONDS,
    ).stdout


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


def _remote(commit: str | None) -> dict[str, Any]:
    """Return the version entry of a source installed from git."""
    return {
        "commit": commit,
        "base": commit,
        "local": False,
        "dirty": False,
        "ahead": None,
    }


def _local(source: str) -> dict[str, str]:
    """Return a placeholder the detached sender replaces with the checkout state."""
    from .setup import _expand

    return {_CHECKOUT_KEY: str(_expand(source))}


def _installed(package: str) -> dict[str, str]:
    """Return a placeholder the detached sender replaces with the package's installed version."""
    return {_INSTALLED_KEY: package}


def _local_sources(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return the checkout placeholder of every tool installed from a local path."""
    from .setup import _is_local_path

    return {
        t.get("name"): _local(str(t.get("source")))
        for t in config.get("tools", [])
        if _is_local_path(str(t.get("source")))
    }


def versions(
    config: dict[str, Any], found: dict[str, str | None] | None = None
) -> dict[str, dict[str, Any]]:
    """Return the version entry of every tracked tool, with placeholders for unresolved ones.

    Args:
        config: The llm-prompts config.
        found: Installed commits by tool name, or None to leave installs as placeholders.
    """
    local = _local_sources(config)
    return {
        n: local.get(n)
        or (_remote(found.get(n)) if found is not None else _installed(n))
        for n in TRACKED
    }


def overlay_versions(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the version entry of every overlay installed from GitHub or a local path."""
    local = _local_sources(config)
    return {
        n: local.get(n) or _installed(n)
        for t in config.get("tools", [])
        if (n := t.get("name")) not in TRACKED
        and _GITHUB_SOURCE.match(str(t.get("source")))
    }


def resolve_versions(body: str) -> str:
    """Replace every placeholder in a JSON body with its checkout or installed state."""

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if _CHECKOUT_KEY in node:
                return _checkout_state(node[_CHECKOUT_KEY])
            if _INSTALLED_KEY in node:
                from .cli import _get_installed_commit

                return _remote(_get_installed_commit(node[_INSTALLED_KEY]))
            return {k: resolve(v) for k, v in node.items()}
        return node

    return json.dumps(resolve(json.loads(body)))


def deliver(body: str) -> None:
    """Resolve placeholders in a body and post it."""
    post(resolve_versions(body))


def _envelope(event: dict[str, Any], install_id: str) -> str:
    """Return the PostHog capture body of an event."""
    return json.dumps({**event, "api_key": POSTHOG_TOKEN, "distinct_id": install_id})


def _post_logged(body: str) -> bool:
    """Post a body, printing the payload and the result to stderr when debugging."""
    debug = is_set(DEBUG_ENV)
    if debug:
        print(f"telemetry payload: {body}", file=sys.stderr)
    delivered = post(body)
    if debug:
        print(f"telemetry sent: {delivered}", file=sys.stderr)
    return delivered


def post_event(event: dict[str, Any], install_id: str) -> bool:
    """Post an event from this process and return whether it arrived.

    Args:
        event: The PostHog event without `api_key` and `distinct_id`.
        install_id: The random install id used as `distinct_id`.
    """
    return _post_logged(_envelope(event, install_id))


def send(
    event: dict[str, Any],
    install_id: str,
    module: str = __name__,
    resolve: Callable[[str], str] = resolve_versions,
) -> None:
    """Post an event from a detached process, or inline when debugging.

    Args:
        event: The PostHog event without `api_key` and `distinct_id`.
        install_id: The random install id used as `distinct_id`.
        module: The module whose `__main__` delivers the body in the detached process.
        resolve: Rewrites the body before an inline debug post.
    """
    body = _envelope(event, install_id)
    if is_set(DEBUG_ENV):
        _post_logged(resolve(body))
        return
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLM_PROMPTS_")}
    cmd = [sys.executable, "-m", module, body]
    Popen(cmd, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True, env=env)


@functools.cache
def resolved_versions() -> dict[str, dict[str, Any]]:
    """Return the resolved version entry of every tracked tool and overlay, once per process."""
    config = read_config()
    body = json.dumps(
        {"versions": versions(config), "overlays": overlay_versions(config)}
    )
    resolved: dict[str, dict[str, Any]] = json.loads(resolve_versions(body))
    return resolved


def context(schema: int) -> dict[str, Any]:
    """Return the platform fields every event carries.

    Args:
        schema: The calling package's event schema number.
    """
    return {
        "os": platform.system(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "schema": schema,
        "$process_person_profile": False,
    }


def bucket(count: int) -> str:
    """Return the power-of-ten range holding a count, such as 10-99."""
    if count <= 0:
        return "0"
    low = 10 ** (len(str(count)) - 1)
    return f"{low}-{low * 10 - 1}"


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
    """Return an exception's type, message and package frames.

    Only llm-prompts and cline-hooks exceptions send their scrubbed message (their type name if empty).
    A `CalledProcessError` sends only its exit status.
    """
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
    own = type(exc).__module__.split(".")[0] in _MESSAGE_PACKAGES
    if isinstance(exc, CalledProcessError):
        item["value"] = f"Command exited with status {exc.returncode}"
    else:
        item["value"] = (scrub(str(exc), config) if own else _WITHHELD) or item["type"]
    return {**item, "stacktrace": {"frames": frames}}


def exception_items(exc: BaseException, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return `exception_item` for `exc` and the exceptions that caused it."""
    return [exception_item(e, config) for e in (exc, *causes(exc))]


def exception_event(
    exc: BaseException, config: dict[str, Any], properties: dict[str, Any]
) -> dict[str, Any]:
    """Return a PostHog exception event for `exc` and its causes, with extra properties."""
    return {
        "event": "$exception",
        "properties": {
            "$exception_list": exception_items(exc, config),
            **properties,
            "$process_person_profile": False,
        },
    }


if __name__ == "__main__":
    deliver(sys.argv[1])
