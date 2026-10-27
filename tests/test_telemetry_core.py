"""Tests for the telemetry helpers shared with other packages."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_prompts import telemetry, telemetry_core

OPT_OUTS = ("DO_NOT_TRACK", "LLM_PROMPTS_NO_TELEMETRY", "CI")
DAY = telemetry_core.OPT_STATE_MAX_AGE


def _state(config_dir: Path) -> dict[str, Any]:
    state: dict[str, Any] = json.loads(
        (config_dir / "telemetry.json").read_text(encoding="utf-8")
    )
    return state


@pytest.mark.real_io
def test_importing_the_core_pulls_in_no_command_modules() -> None:
    script = (
        "import sys, llm_prompts.telemetry_core;"
        "print([m for m in ('install', 'manifest', 'setup', 'cli')"
        " if f'llm_prompts.{m}' in sys.modules])"
    )

    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "[]"


@pytest.mark.parametrize(
    ("env", "opted_out"),
    [({}, False), ({"DO_NOT_TRACK": "1"}, True), ({"CI": "1"}, True)],
)
def test_begin_records_the_opt_out_state_and_keeps_the_install_id(
    telemetry_popen: MagicMock,
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    opted_out: bool,
) -> None:
    for name in OPT_OUTS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    before = time.time()

    telemetry.Run(lambda _: None).begin("update", [])

    state = _state(isolated_config_dir)
    assert state["install_id"] == "synthetic-id"
    assert state["opted_out"] is opted_out
    assert before <= state["at"] <= time.time()


def test_the_first_run_keeps_the_recorded_opt_out_state(
    telemetry_popen: MagicMock, isolated_config_dir: Path
) -> None:
    (isolated_config_dir / "telemetry.json").unlink()

    with telemetry.Run(lambda _: None) as run:
        run.begin("update", [])

    state = _state(isolated_config_dir)
    assert state["opted_out"] is False
    assert state["install_id"]
    assert telemetry_popen.call_count == 0


@pytest.mark.parametrize(
    ("state", "age", "allowed"),
    [
        (None, None, False),
        ({"install_id": "x"}, None, False),
        ({"opted_out": False, "at": "now"}, None, False),
        ({"opted_out": True}, 60, False),
        ({"opted_out": False}, DAY + 1, False),
        ({"opted_out": False}, -60, False),
        ({"opted_out": False}, DAY - 60, True),
    ],
)
def test_sending_needs_a_recent_record_that_is_not_opted_out(
    isolated_config_dir: Path,
    state: dict[str, Any] | None,
    age: float | None,
    allowed: bool,
) -> None:
    if state is not None:
        record = {**state, **({} if age is None else {"at": time.time() - age})}
        (isolated_config_dir / "telemetry.json").write_text(json.dumps(record))

    assert telemetry_core.may_send() is allowed


def _raise_from(module: str, filename: str) -> BaseException:
    """Return an exception raised by a function that looks defined in `module`."""
    code = compile("def fail():\n    raise RuntimeError\n", filename, "exec")
    namespace: dict[str, Any] = {"__name__": module}
    exec(code, namespace)  # noqa: S102
    try:
        namespace["fail"]()
    except RuntimeError as error:
        return error
    raise AssertionError


@pytest.mark.parametrize(
    ("module", "filename", "expected"),
    [
        ("llm_prompts.cli", "/site/llm_prompts/cli.py", ["llm_prompts/cli.py"]),
        ("mcp_memory.server", "/site/mcp_memory/server.py", ["mcp_memory/server.py"]),
        ("other.mod", "/site/other/mod.py", []),
    ],
)
def test_exceptions_report_frames_of_both_packages_only(
    module: str, filename: str, expected: list[str]
) -> None:
    error = _raise_from(module, filename)

    [item] = telemetry_core.exception_items(error, {})

    frames = [f["filename"] for f in item["stacktrace"]["frames"]]
    assert frames == expected
