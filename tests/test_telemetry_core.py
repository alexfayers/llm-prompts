"""Tests for the telemetry helpers shared with other packages."""

from __future__ import annotations

import json
import runpy
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


def test_a_body_without_placeholders_resolves_without_the_command_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "llm_prompts.cli", None)
    body = json.dumps({"event": "run", "properties": {"os": "Linux"}})

    assert json.loads(telemetry_core.resolve_versions(body)) == json.loads(body)


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


def test_a_sent_versions_payload_is_resolved_without_paths(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = {"tools": [{"name": "mcp-memory", "source": str(tmp_path)}]}
    monkeypatch.setattr("llm_prompts.cli._get_installed_commit", lambda _: "a" * 40)
    posted = MagicMock()
    monkeypatch.setattr("llm_prompts.telemetry_core.post", posted)
    monkeypatch.setattr(
        "llm_prompts.telemetry_core.run",
        MagicMock(side_effect=subprocess.SubprocessError),
    )

    telemetry_core.send(
        {"event": "e", "properties": {"versions": telemetry_core.versions(config)}},
        "id-1",
    )
    telemetry_core.deliver(telemetry_popen.call_args.args[0][3])

    body = posted.call_args.args[0]
    versions = json.loads(body)["properties"]["versions"]
    assert set(versions) == set(telemetry_core.TRACKED)
    assert versions["mcp-memory"]["local"] is True
    assert versions["llm-prompts"]["commit"] == "a" * 40
    assert str(tmp_path) not in body


def test_the_detached_sender_posts_each_event_once_without_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = {"tools": [{"name": "mcp-memory", "source": str(tmp_path)}]}
    body = json.dumps({"properties": {"versions": telemetry_core.versions(config)}})
    urlopen = MagicMock()
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(
        "subprocess.run", MagicMock(side_effect=subprocess.SubprocessError)
    )
    monkeypatch.setattr("llm_prompts.cli._get_installed_commit", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["telemetry_core", body])
    monkeypatch.delitem(sys.modules, "llm_prompts.telemetry_core")

    runpy.run_module("llm_prompts.telemetry_core", run_name="__main__")

    urlopen.assert_called_once()
    assert str(tmp_path).encode() not in urlopen.call_args.args[0].data


def test_post_event_adds_the_envelope_and_returns_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted = MagicMock(return_value=False)
    monkeypatch.setattr("llm_prompts.telemetry_core.post", posted)

    delivered = telemetry_core.post_event({"event": "e"}, "id-1")

    body = json.loads(posted.call_args.args[0])
    assert delivered is False
    assert body["api_key"] == telemetry_core.POSTHOG_TOKEN
    assert body["distinct_id"] == "id-1"


def test_post_event_prints_the_payload_then_the_result_when_debugging(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(telemetry_core.DEBUG_ENV, "1")
    monkeypatch.setattr("llm_prompts.telemetry_core.post", lambda _: True)

    telemetry_core.post_event({"event": "e"}, "id-1")

    err = capsys.readouterr().err
    assert err.startswith("telemetry payload: {")
    assert err.endswith("telemetry sent: True\n")


@pytest.mark.parametrize(
    ("env", "age", "expected"),
    [({}, 60, "id-1"), ({"DO_NOT_TRACK": "1"}, 60, None), ({}, DAY + 1, None)],
)
def test_active_install_id_needs_telemetry_on_and_a_fresh_record(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    age: float,
    expected: str | None,
) -> None:
    for name in OPT_OUTS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    record = {"install_id": "id-1", "opted_out": False, "at": time.time() - age}
    (isolated_config_dir / "telemetry.json").write_text(json.dumps(record))

    assert telemetry_core.active_install_id() == expected


def test_resolved_versions_name_every_tracked_tool_once_without_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = {"tools": [{"name": "mcp-memory", "source": str(tmp_path)}]}
    git = MagicMock(side_effect=subprocess.SubprocessError)
    monkeypatch.setattr("llm_prompts.telemetry_core.read_config", lambda: config)
    monkeypatch.setattr("llm_prompts.telemetry_core.run", git)
    monkeypatch.setattr("llm_prompts.cli._get_installed_commit", lambda _: None)
    telemetry_core.resolved_versions.cache_clear()

    first = telemetry_core.resolved_versions()
    calls = git.call_count
    telemetry_core.resolved_versions()
    telemetry_core.resolved_versions.cache_clear()

    assert set(first) == {"versions", "overlays"}
    assert set(first["versions"]) == set(telemetry_core.TRACKED)
    assert str(tmp_path) not in json.dumps(first)
    assert git.call_count == calls


def test_our_exception_without_a_message_sends_its_type_name() -> None:
    own = type("OwnError", (Exception,), {"__module__": "llm_prompts.synthetic"})

    [item] = telemetry_core.exception_items(own(), {})

    assert item["value"] == "OwnError"


def test_our_own_exception_keeps_its_scrubbed_message() -> None:
    own = type("OwnError", (Exception,), {"__module__": "cline_hooks.synthetic"})

    [item] = telemetry_core.exception_items(own("own detail"), {})

    assert item["value"] == "own detail"


def test_called_process_error_sends_only_its_exit_status() -> None:
    error = subprocess.CalledProcessError(7, ["tool", "--flag", "value"])

    [item] = telemetry_core.exception_items(error, {})

    assert item["value"] == "Command exited with status 7"


def test_mcp_memory_exception_sends_its_type_with_a_fixed_message() -> None:
    other = type("MemoryError", (Exception,), {"__module__": "mcp_memory.synthetic"})

    [item] = telemetry_core.exception_items(other("entity 'name' not found"), {})

    assert (item["type"], item["value"]) == ("MemoryError", "<message withheld>")


def test_another_exception_sends_its_type_with_a_fixed_message() -> None:
    [item] = telemetry_core.exception_items(ValueError("other detail"), {})

    assert (item["type"], item["value"]) == ("ValueError", "<message withheld>")


@pytest.mark.parametrize(("count", "bucket"), [(0, "0"), (7, "1-9"), (42, "10-99")])
def test_bucket_names_the_power_of_ten_range(count: int, bucket: str) -> None:
    assert telemetry_core.bucket(count) == bucket
