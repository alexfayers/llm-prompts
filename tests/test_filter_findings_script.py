"""Tests for the pr-review skill's severity filter script."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from conftest import FakeSubprocess

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
    mod: ModuleType, capsys: pytest.CaptureFixture[str], stdin: str, *args: str
) -> tuple[int, str]:
    with (
        patch("sys.argv", ["filter_findings.py", *args]),
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


def test_scope_prints_every_diff_and_untracked_paths(
    mod: ModuleType,
    capsys: pytest.CaptureFixture[str],
    fake_subprocess: FakeSubprocess,
) -> None:
    fake_subprocess.on("diff", "HEAD", stdout="uncommitted diff\n")
    fake_subprocess.on("diff", "@{u}...HEAD", stdout="unpushed diff\n")
    fake_subprocess.on("diff", "origin/main...HEAD", stdout="base diff\n")
    fake_subprocess.on("gh", "pr", "view", stdout="main\n")
    fake_subprocess.on(
        "ls-files", "--others", "--exclude-standard", "--", ":/", stdout="a.py\n"
    )
    code, out = _run(mod, capsys, "", "--scope")
    assert code == 0
    for text in ("uncommitted diff", "unpushed diff", "base diff", "a.py"):
        assert text in out


def test_scope_without_upstream_or_pr_diffs_against_default_branch(
    mod: ModuleType,
    capsys: pytest.CaptureFixture[str],
    fake_subprocess: FakeSubprocess,
) -> None:
    fake_subprocess.on("rev-parse", "--abbrev-ref", "@{u}", returncode=128)
    fake_subprocess.on("gh", "pr", "view", returncode=1)
    fake_subprocess.on("symbolic-ref", stdout="origin/dev\n")
    fake_subprocess.on("diff", "origin/dev...HEAD", stdout="base diff\n")
    code, out = _run(mod, capsys, "", "--scope")
    assert code == 0
    assert out.count("base diff") == 1
    assert not fake_subprocess.matching("diff", "@{u}...HEAD")


def test_scope_keeps_default_branch_diff_when_pr_targets_another_branch(
    mod: ModuleType,
    capsys: pytest.CaptureFixture[str],
    fake_subprocess: FakeSubprocess,
) -> None:
    fake_subprocess.on("rev-parse", "--abbrev-ref", "@{u}", returncode=128)
    fake_subprocess.on("gh", "pr", "view", stdout="dev\n")
    fake_subprocess.on("symbolic-ref", stdout="origin/main\n")
    fake_subprocess.on("diff", "origin/dev...HEAD", stdout="pr base diff\n")
    fake_subprocess.on("diff", "origin/main...HEAD", stdout="default branch diff\n")
    code, out = _run(mod, capsys, "", "--scope")
    assert code == 0
    assert "pr base diff" in out
    assert "default branch diff" in out


def test_scope_git_failure_exits_one_with_one_line_message(
    mod: ModuleType,
    capsys: pytest.CaptureFixture[str],
    fake_subprocess: FakeSubprocess,
) -> None:
    fake_subprocess.on("diff", "HEAD", returncode=128, stderr="fatal: not a repo\n")
    with patch("sys.argv", ["filter_findings.py", "--scope"]):
        code = mod.main()
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == "git diff HEAD failed: fatal: not a repo\n"
