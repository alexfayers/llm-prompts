"""Tests for the codemode-error-header pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
    / "codemode-error-header.ts"
)
_HARNESS = Path(__file__).parent / "codemode_error_header_harness.mjs"


def _can_strip_types() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run(
        [node, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _can_strip_types(), reason="node with type stripping missing"
)


def _text(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _failed(*output: str, tool: str = "codemode") -> dict[str, Any]:
    header = "Script failed\nWall time 0.1 seconds\nOutput:\n"
    return {
        "toolName": tool,
        "isError": True,
        "content": [_text(header), *map(_text, output)],
    }


def _handle(tmp_path: Path, events: list[dict[str, Any]]) -> list[Any]:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"script": str(_SCRIPT), "events": events}))
    done = subprocess.run(
        ["node", str(_HARNESS), str(config)],
        check=True,
        capture_output=True,
        text=True,
    )
    output: dict[str, Any] = json.loads(done.stdout)
    assert "error" not in output, output["error"]
    results: list[Any] = output["results"]
    return results


def test_failed_codemode_header_carries_the_first_error_line(tmp_path: Path) -> None:
    stack = "Script error:\nError: boom: widget table missing\n    at <anonymous> (codemode.js:1:39)"
    [result] = _handle(tmp_path, [_failed("partial output\n\n" + stack)])
    assert result["content"][0]["text"] == (
        "Script failed: Error: boom: widget table missing\nWall time 0.1 seconds\nOutput:\n"
    )
    assert result["content"][1:] == _failed("partial output\n\n" + stack)["content"][1:]


def _untouched() -> list[dict[str, Any]]:
    success = {
        "toolName": "codemode",
        "isError": False,
        "content": [
            _text("Script completed\nWall time 0.1 seconds\nOutput:\n"),
            _text("2"),
        ],
    }
    no_error_text = {
        "toolName": "codemode",
        "isError": True,
        "content": [_text("Script failed\nWall time 0.1 seconds\nOutput:\n")],
    }
    rejected_input = {
        "toolName": "codemode",
        "isError": True,
        "content": [_text("Invalid options")],
    }
    return [
        success,
        no_error_text,
        rejected_input,
        _failed("Script error:\nError: nope", tool="bash"),
    ]


def test_everything_else_is_left_alone(tmp_path: Path) -> None:
    assert _handle(tmp_path, _untouched()) == [None] * 4


def test_whole_first_error_line_is_passed_through_without_a_cap(
    tmp_path: Path,
) -> None:
    long_error = "Error: " + "x" * 500
    [result] = _handle(tmp_path, [_failed(f"Script error:\n{long_error}\n    at y")])
    assert result["content"][0]["text"].startswith(f"Script failed: {long_error}\n")
