"""Retry git and gh calls that fail on a transient network error."""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable
from typing import Any

TRANSIENT_FAILURE = re.compile(
    r"could not resolve host|failed to connect|couldn't connect|connection reset|connection refused"
    r"|connection timed out|operation timed out|early eof|rpc failed|tls handshake"
    r"|(?:returned error|HTTP):? 50[234]\b",
    re.IGNORECASE,
)
NETWORK_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.0


def with_retries[T](call: Callable[[], T]) -> T:
    """Run a network call and return its result, retrying transient failures with backoff."""
    for attempt in range(1, NETWORK_ATTEMPTS):
        try:
            return call()
        except subprocess.CalledProcessError as error:
            if not TRANSIENT_FAILURE.search(error.stderr or ""):
                raise
            time.sleep(RETRY_DELAY_SECONDS * attempt)
    return call()


def run_with_retries(
    argv: list[str], *, check: bool = False, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    """Run a network command like ``subprocess.run``, retrying transient failures with backoff."""
    try:
        return with_retries(lambda: subprocess.run(argv, check=True, **kwargs))
    except subprocess.CalledProcessError as error:
        if check:
            raise
        return subprocess.CompletedProcess(
            argv, error.returncode, error.stdout, error.stderr
        )
