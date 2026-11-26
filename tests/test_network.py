"""Tests for transient network failure retries."""

from __future__ import annotations

import subprocess

import pytest
from conftest import FakeSubprocess

from llm_prompts import network
from llm_prompts.setup import GIT_TIMEOUT


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


def test_fail_fast_limits_only_ls_remote_fetch_and_clone(
    fake_subprocess: FakeSubprocess,
) -> None:
    with network.fail_fast():
        for argv in (
            ["git", "ls-remote", "u"],
            ["git", "-C", "r", "fetch"],
            ["git", "clone", "u", "d"],
            ["git", "push", "u"],
        ):
            network.run_with_retries(argv, timeout=GIT_TIMEOUT)
    assert [kwargs["timeout"] for _, kwargs in fake_subprocess.calls] == [
        network.FAIL_FAST_TIMEOUT,
        network.FAIL_FAST_TIMEOUT,
        network.FAIL_FAST_TIMEOUT,
        GIT_TIMEOUT,
    ]


def test_run_with_retries_never_waits_on_a_terminal_prompt(
    fake_subprocess: FakeSubprocess,
) -> None:
    network.run_with_retries(["git", "fetch"], env={"KEEP": "1"})
    network.run_with_retries(["git", "fetch"], input="data")
    (_, plain), (_, with_input) = fake_subprocess.calls
    assert plain["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert plain["env"]["KEEP"] == "1"
    assert plain["stdin"] == subprocess.DEVNULL
    assert with_input["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert "stdin" not in with_input
