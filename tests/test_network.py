"""Tests for transient network failure retries."""

from __future__ import annotations

import subprocess

import pytest

from llm_prompts import network


@pytest.mark.parametrize(
    ("stderr", "transient"),
    [
        ("fatal: unable to access 'u': Could not resolve host: github.com", True),
        ("fatal: unable to access 'u': Failed to connect to github.com", True),
        ("fatal: unable to access 'u': Couldn't connect to server", True),
        ("error: RPC failed; curl 56 recv failure", True),
        ("fatal: unable to access 'u': The requested URL returned error: 503", True),
        ("HTTP 502: Bad Gateway", True),
        ("fatal: unable to access 'u': The requested URL returned error: 403", False),
        ("fatal: repository 'u' not found: HTTP 404", False),
        ("fatal: bad object 5028f1a6c0de", False),
    ],
)
def test_transient_failure_pattern(stderr: str, transient: bool) -> None:
    assert bool(network.TRANSIENT_FAILURE.search(stderr)) is transient


def test_with_retries_retries_a_transient_failure() -> None:
    failures = [
        subprocess.CalledProcessError(128, "git", stderr="Connection reset by peer")
    ]

    def call() -> str:
        if failures:
            raise failures.pop()
        return "ok"

    assert network.with_retries(call) == "ok"


def test_with_retries_retries_a_timeout_and_gives_up_after_the_last_attempt() -> None:
    attempts = 0

    def call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < network.NETWORK_ATTEMPTS:
            raise subprocess.TimeoutExpired("git", 30)
        return "ok"

    assert network.with_retries(call) == "ok"

    def always_times_out() -> str:
        raise subprocess.TimeoutExpired("git", 30)

    with pytest.raises(subprocess.TimeoutExpired):
        network.with_retries(always_times_out)
