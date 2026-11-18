"""Run ``llm-prompts update`` in the background at session start, when it is safe to."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from cline_hooks.plugins.checkout_lock import LOCK_TTL_SECONDS
from cline_hooks.state.paths import get_data_dir
from platformdirs import user_data_dir

from .main_sync import UPSTREAM, run_git, unreleased
from .plugins import _checkout_dir
from .setup import _expand, _is_local_path, config_path, read_config

STATE_DIR = Path(user_data_dir("llm-prompts"))
_CHECKOUT_LOCKS = get_data_dir() / "checkout-locks.json"
LOCK_FD_ENV = "LLM_PROMPTS_UPDATE_LOCK_FD"
FORK_IDLE_SECONDS = 60 * 60
FORK_RUNNING = "fork"
UPDATE_RUNNING = "Another llm-prompts update is running. Rerun once it finishes."


def _failure_file() -> Path:
    return STATE_DIR / "auto-update-failed.json"


def record_failure(fingerprint: str, reason: str) -> None:
    """Remember that the automatic update failed at these installed versions."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _failure_file().write_text(
        json.dumps({"fingerprint": fingerprint, "reason": reason}), encoding="utf-8"
    )


def failure(fingerprint: str) -> str | None:
    """Return why the automatic update failed at these installed versions, or None."""
    try:
        record = json.loads(_failure_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record.get("reason") if record.get("fingerprint") == fingerprint else None


def blocker(fingerprint: str) -> str | None:
    """Return the kind of what blocks an automatic update, or None when it may run.

    Args:
        fingerprint: The installed versions, as ``_installed_fingerprint`` returns them.
    """
    if not config_path().exists():
        return "off"
    config = read_config()
    settings = config.get("update", {})
    if not isinstance(settings, dict):
        return "off"
    auto = settings.get("auto", True)
    if not isinstance(auto, bool):
        return "off"
    if not auto:
        return "off"
    if failure(fingerprint) is not None:
        return "failed"
    if _fork_running():
        return FORK_RUNNING
    held = _held_git_dirs()
    checkouts = [
        (str(tool.get("name")), _expand(str(tool["source"])), _has_local_changes)
        for tool in config.get("tools", [])
        if _is_local_path(str(tool.get("source", "")))
    ]
    plugins = config.get("plugins", [])
    checkouts += [
        (str(plugin.get("name")), checkout, _has_unpushed_changes)
        for plugin in plugins
        if isinstance(plugins, list) and isinstance(plugin, dict)
        if ((checkout := _checkout_dir(str(plugin.get("name", "")))) / ".git").is_dir()
    ]
    for name, repo, has_changes in checkouts:
        git_dir = (repo / ".git").resolve()
        if any(path == git_dir or git_dir in path.parents for path in held):
            return "session"
        if has_changes(repo):
            return "local-changes"
    return None


def _fork_running() -> bool:
    """Whether a pi-context fork run is unfinished and its handshake, seed or cold session changed within ``FORK_IDLE_SECONDS``.

    shortcut: a run killed without its ``finished`` mark counts until it goes idle,
    upgrade to a pid in the handshake when pi-context records one.
    """
    agent_dir = Path(
        os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent"
    )
    cutoff = time.time() - FORK_IDLE_SECONDS
    for handshake in (agent_dir / "pi-context").glob("*/handshake.json"):
        run = handshake.parent
        if (run / "finished").exists():
            continue
        mtimes = [
            f.stat().st_mtime
            for f in (handshake, run / "seed.jsonl", *(run / "session").glob("*"))
            if f.exists()
        ]
        if mtimes and max(mtimes) > cutoff:
            return True
    return False


def _held_git_dirs() -> list[Path]:
    """Return the git dirs that live agent sessions hold, from cline-hooks' checkout locks."""
    try:
        locks = json.loads(_CHECKOUT_LOCKS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [
        Path(lock["git_dir"]).resolve()
        for lock in locks
        if isinstance(lock, dict) and _alive(lock)
    ]


def _alive(lock: dict[str, object]) -> bool:
    """Whether a checkout lock's session still runs, the way cline-hooks decides it."""
    pid, at = lock.get("pid"), lock.get("at")
    if not isinstance(at, (int, float)) or time.time() - at >= LOCK_TTL_SECONDS:
        return False
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
    return True


def _has_local_changes(repo: Path) -> bool:
    """Whether a local checkout holds edits, or commits the release it follows lacks."""
    if run_git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        return True
    ahead = run_git(repo, "rev-list", f"{UPSTREAM}..HEAD")
    return ahead.returncode != 0 or bool(set(ahead.stdout.split()) - unreleased(repo))


def _has_unpushed_changes(repo: Path) -> bool:
    """Whether a plugin checkout holds edits, or commits no remote branch has."""
    if run_git(repo, "status", "--porcelain").stdout.strip():
        return True
    unpushed = run_git(repo, "rev-list", "HEAD", "--not", "--remotes")
    return unpushed.returncode != 0 or bool(unpushed.stdout.strip())


def _handed_over_lock(lock_path: Path) -> bool:
    """Whether this process inherited the open lock file from the process that holds the lock."""
    try:
        fd = int(os.environ[LOCK_FD_ENV])
        same_file = os.path.samestat(os.fstat(fd), lock_path.stat())
        if same_file:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return same_file
    except (KeyError, ValueError, OSError):
        return False


@contextmanager
def lock() -> Iterator[bool]:
    """Yield True while this process holds the update lock, False if another holds it.

    The holder keeps the lock file open across exec and hands it to children
    through ``LOCK_FD_ENV``, so a restart in place or an ``update --auto`` child
    keeps the lock its parent took.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = STATE_DIR / "auto-update.lock"
    if _handed_over_lock(lock_path):
        yield True
        return
    with lock_path.open("a") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        os.set_inheritable(lock_file.fileno(), True)
        os.environ[LOCK_FD_ENV] = str(lock_file.fileno())
        try:
            yield True
        finally:
            os.environ.pop(LOCK_FD_ENV, None)


def _fingerprint() -> str:
    """Return the installed versions, so a partial update is not retried at its new versions."""
    from .cli import _installed_fingerprint

    return _installed_fingerprint()


def run(fingerprint: str) -> None:
    """Run ``llm-prompts update --auto`` once, logging its output and recording a failure."""
    with lock() as held:
        if not held or blocker(fingerprint) is not None:
            return
        result = subprocess.run(
            [_script(), "update", "--auto"],
            pass_fds=(int(os.environ[LOCK_FD_ENV]),),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        (STATE_DIR / "auto-update.log").write_text(output, encoding="utf-8")
        if result.returncode:
            lines = output.strip().splitlines()
            record_failure(
                _fingerprint(), lines[-1] if lines else f"exit {result.returncode}"
            )
        else:
            _failure_file().unlink(missing_ok=True)


def _script() -> str:
    """Return the ``llm-prompts`` console script of this install, which ``update`` can re-exec."""
    beside = Path(sys.executable).with_name("llm-prompts")
    return (
        str(beside) if beside.exists() else shutil.which("llm-prompts") or "llm-prompts"
    )


def start(fingerprint: str) -> str:
    """Start ``run`` in a detached process unless something blocks it, and return ``started`` or the blocker's kind."""
    if (blocked := blocker(fingerprint)) is not None:
        return blocked
    subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from llm_prompts.auto_update import run; run(sys.argv[1])",
            fingerprint,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return "started"
