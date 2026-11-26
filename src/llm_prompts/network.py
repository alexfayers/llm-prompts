"""Retry git and gh calls that fail on a transient network error."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

TRANSIENT_FAILURE = re.compile(
    r"could not resolve host|failed to connect|couldn't connect|connection reset|connection refused"
    r"|connection timed out|operation timed out|early eof|rpc failed|tls handshake"
    r"|(?:returned error|HTTP):? 50[234]\b",
    re.IGNORECASE,
)
NETWORK_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.0
FAIL_FAST_TIMEOUT = 5
_FAIL_FAST_COMMANDS = frozenset({"ls-remote", "fetch", "clone"})
_failing_fast = threading.Event()


@contextmanager
def fail_fast() -> Iterator[None]:
    """Run each ``ls-remote``, ``fetch`` and ``clone`` once, within ``FAIL_FAST_TIMEOUT`` seconds, while the context is open."""
    _failing_fast.set()
    try:
        yield
    finally:
        _failing_fast.clear()


def stderr_text(error: subprocess.CalledProcessError) -> str:
    """Return a failed call's stderr as text, whether captured as str or bytes."""
    stderr = error.stderr or ""
    return stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr


def with_retries[T](call: Callable[[], T]) -> T:
    """Run a network call and return its result, retrying timeouts and transient failures with backoff."""
    for attempt in range(1, NETWORK_ATTEMPTS):
        try:
            return call()
        except subprocess.TimeoutExpired:
            pass
        except subprocess.CalledProcessError as error:
            if not TRANSIENT_FAILURE.search(stderr_text(error)):
                raise
        time.sleep(RETRY_DELAY_SECONDS * attempt)
    return call()


def run_with_retries(
    argv: list[str], *, check: bool = False, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    """Run a network command like ``subprocess.run``, retrying transient failures with backoff.

    The command never waits on a terminal credential prompt: git gets ``GIT_TERMINAL_PROMPT=0``, and stdin is
    ``/dev/null`` unless ``input`` is given.
    """
    kwargs["env"] = {**(kwargs.get("env") or os.environ), "GIT_TERMINAL_PROMPT": "0"}
    if kwargs.get("input") is None:
        kwargs.setdefault("stdin", subprocess.DEVNULL)
    fast = _failing_fast.is_set() and not _FAIL_FAST_COMMANDS.isdisjoint(argv)
    if fast:
        kwargs["timeout"] = FAIL_FAST_TIMEOUT

    def call() -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, check=True, **kwargs)

    try:
        return call() if fast else with_retries(call)
    except subprocess.CalledProcessError as error:
        if check:
            raise
        return subprocess.CompletedProcess(
            argv, error.returncode, error.stdout, error.stderr
        )
