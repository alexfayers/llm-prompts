"""Tests for the entry points the shared prompt-checks workflow calls."""

from __future__ import annotations

from pathlib import Path

from llm_prompts.install import prompts_dir
from llm_prompts.size_guard import check
from llm_prompts.size_report import compare, render_markdown


def test_check_and_size_report_work_as_the_workflow_runs_them(
    synthetic_prompts_root: Path,
) -> None:
    roots = [synthetic_prompts_root]

    result = check(roots)
    report = render_markdown(compare(result.artifacts, result.artifacts, roots, roots))

    assert prompts_dir("llm_prompts").is_dir()
    assert result.passed, result.report
    assert isinstance(result.stale, list)
    assert "**Prompt size**" in report
