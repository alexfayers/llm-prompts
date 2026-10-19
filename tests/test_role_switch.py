"""Tests for the role-switch pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

_HARNESS = Path(__file__).with_name("context_total_harness.mjs")
_SCRIPT = _HARNESS.parents[1] / "src/llm_prompts/prompts/pi/extensions/role-switch.ts"
_NODE = shutil.which("node")
_SONNET = {"model": "prov/sonnet", "efforts": {"low": "low", "high": "high"}}
_LEAD = {"model": {"provider": "prov", "id": "lead"}, "thinking": "medium"}

pytestmark = pytest.mark.skipif(_NODE is None, reason="node missing")


def _run(tmp_path: Path, steps: list[dict[str, Any]], **state: Any) -> dict[str, Any]:
    variants = {"worker": {"sonnet": _SONNET}}
    (tmp_path / "agent-role-variants.json").write_text(json.dumps(variants))
    pi = {"$pi": "pi", "state": {**_LEAD, **state}, "allTools": state.get("tools", [])}
    steps = [{"fn": "default", "args": [pi]}, *steps]
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"script": str(_SCRIPT), "agentDir": str(tmp_path), "steps": steps})
    )
    done = subprocess.run(
        [str(_NODE), str(_HARNESS), str(config)], check=True, capture_output=True
    )
    output = json.loads(done.stdout)
    assert "error" not in output, output["error"]
    return dict(output["results"])


def _delegate(
    tmp_path: Path, definition: str, enum: list[str] | None = None, **state: Any
) -> dict[str, Any]:
    tool = {"name": "delegate_agent", "parameters": _schema(enum or [])}
    call = {"toolName": "delegate_agent", "input": {"definition": definition}}
    emit = {"pi": "pi", "payload": call, "ctx": {"$modelCtx": "pi"}}
    steps: list[dict[str, Any]] = [
        *([{"emit": "session_start", "pi": "pi"}] if enum else []),
        {**emit, "emit": "tool_call", "as": "call", "payloadAs": "sent"},
        {"switches": "pi", "as": "during"},
        {**emit, "emit": "tool_execution_end"},
        {"switches": "pi", "as": "after"},
    ]
    results = _run(tmp_path, steps, tools=[tool], **state)
    for key in ("during", "after"):
        results[key] = (results[key]["model"]["id"], results[key]["thinking"])
    return results


def _schema(enum: list[str]) -> dict[str, Any]:
    return {"properties": {"definition": {"enum": enum}}}


def test_session_start_adds_variant_names_to_the_enum(tmp_path: Path) -> None:
    tool = {"name": "delegate_agent", "parameters": _schema(["Explore", "worker"])}
    steps = [{"emit": "session_start", "pi": "pi"}, {"allToolsOf": "pi", "as": "tools"}]
    results = _run(tmp_path, steps, tools=[tool])
    enum = results["tools"][0]["parameters"]["properties"]["definition"]["enum"]
    assert enum == ["Explore", "worker", "worker@sonnet:low", "worker@sonnet:high"]


def test_delegation_switches_the_model_then_restores(tmp_path: Path) -> None:
    results = _delegate(tmp_path, "worker@sonnet:high", ["worker"])
    assert "call" not in results
    assert results["sent"]["input"]["definition"] == "worker"
    assert results["during"] == ("sonnet", "high")
    assert results["after"] == ("lead", "medium")


@pytest.mark.parametrize(
    ("name", "refuse"), [("worker@sonnet:low", ["sonnet"]), ("worker", [])]
)
def test_failed_switch_or_plain_role_is_blocked(
    tmp_path: Path, name: str, refuse: list[str]
) -> None:
    results = _delegate(tmp_path, name, ["worker"], refuse=refuse)
    assert results["call"]["block"] is True
    assert results["after"] == ("lead", "medium")


@pytest.mark.parametrize(
    ("name", "enum"),
    [
        ("worker@sonnet:max", ["worker"]),
        ("worker@sonnet:toString", ["worker"]),
        ("constructor@a:b", ["worker"]),
        ("worker@sonnet:high", ["Explore"]),
    ],
)
def test_unlisted_names_are_left_alone(
    tmp_path: Path, name: str, enum: list[str]
) -> None:
    results = _delegate(tmp_path, name, enum)
    assert "call" not in results
    assert results["sent"]["input"]["definition"] == name
    assert results["during"] == ("lead", "medium")
