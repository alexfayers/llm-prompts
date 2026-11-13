"""Tests for the pr-review skill's severity filter script."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "shared"
    / "skills"
    / "pr-review"
    / "filter_findings.py"
)


@pytest.fixture
def mod() -> ModuleType:
    """Load the filter_findings script as a module."""
    spec = importlib.util.spec_from_file_location("filter_findings", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(
    mod: ModuleType, capsys: pytest.CaptureFixture[str], stdin: str
) -> tuple[int, str]:
    with (
        patch("sys.argv", ["filter_findings.py"]),
        patch("sys.stdin", io.StringIO(stdin)),
    ):
        code = mod.main()
    return code, capsys.readouterr().out


def test_drops_findings_below_severity_three(
    mod: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = {"severity": 3, "path": "a.py:1", "text": "keep"}
    dropped = {"severity": 4, "path": "b.py:2", "text": "drop"}
    code, out = _run(mod, capsys, json.dumps([kept, dropped]))
    assert code == 0
    assert json.loads(out) == [kept]


def test_sorts_kept_findings_most_severe_first(
    mod: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    findings = [{"severity": s} for s in (3, 1, 2)]
    _, out = _run(mod, capsys, json.dumps(findings))
    assert [f["severity"] for f in json.loads(out)] == [1, 2, 3]


@pytest.mark.parametrize(
    "stdin",
    [
        "not json",
        '{"severity": 1}',
        '[{"severity": 0}]',
        '[{"severity": 6}]',
        '[{"severity": "2"}]',
        '[{"severity": true}]',
        '[{"path": "a.py:1"}]',
    ],
)
def test_bad_input_exits_one_without_output(
    mod: ModuleType, capsys: pytest.CaptureFixture[str], stdin: str
) -> None:
    code, out = _run(mod, capsys, stdin)
    assert code == 1
    assert out == ""
