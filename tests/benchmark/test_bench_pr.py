import re
import subprocess
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchmark.test_bench_report import full_report, row
from llm_prompts import contribute, github_api, telemetry
from llm_prompts.benchmark.report import pr
from llm_prompts.benchmark.report.compare import JudgeReason, Report

BODY = (
    "## What\n\n- feat: x\n\n## Why\n\n- Because.\n\n## Dependencies\n\nDepends on #1\n"
)


DEPENDS_ON = "Depends on https://example.test/pull/1\n"
TRAILING_DEPENDS_BODY = f"## What\n\n- feat: x\n\n## Why\n\n- Because.\n\n{DEPENDS_ON}"


@pytest.mark.parametrize(
    ("body", "after_section"),
    [(BODY, "## Dependencies\n"), (TRAILING_DEPENDS_BODY, DEPENDS_ON)],
    ids=["dependencies-heading", "trailing-depends-on"],
)
def test_section_replaces_the_existing_one_or_goes_before_dependencies(
    body: str, after_section: str
) -> None:
    attached = pr.with_section(body, "## Benchmark\n\n- First.\n")
    replaced = pr.with_section(attached, "## Benchmark\n\n- Second.\n")

    assert f"- Because.\n\n## Benchmark\n\n- First.\n\n{after_section}" in attached
    assert replaced == attached.replace("First", "Second")


def test_section_survives_a_what_rewrite() -> None:
    attached = pr.with_section(TRAILING_DEPENDS_BODY, "## Benchmark\n\n- Second.\n")
    commit = contribute.Commit("abc", "feat: y", ())

    rewritten = contribute.rewrite_what(
        attached, [commit], ["https://example.test/pull/1"]
    )

    assert rewritten.count("Depends on") == 1
    assert "## Benchmark\n\n- Second." in rewritten


def public_report() -> Report:
    rows = [
        {**row("a"), "reused_from": "20260101-000000-aaaa"},
        row("b", error="boom at /home/someone/secret.py"),
        row("b"),
        row("b"),
    ]
    reason = JudgeReason("s1", "claude", "b", 0, "judge said the secret-reason")
    return replace(
        full_report(rows),
        judge_reasons=(reason,),
        prompt_size_missing="No base prompts at `/home/someone/src` to compare against.",
    )


def test_section_is_a_short_public_summary_with_the_full_report_folded_below() -> None:
    report = public_report()

    section = pr.section(report)
    bullets = [line for line in section.splitlines() if line.startswith("- ")]
    folded = section.split("<details>")[1]

    assert section.startswith("## Benchmark\n\n")
    assert 1 <= len(bullets) <= 3
    assert all(bullet.endswith(".") for bullet in bullets)
    assert "<!--" not in section
    assert pr.leaks(section) == []
    assert report.run_id not in section
    assert "20260101-000000-aaaa" not in section
    assert "reused" in section
    assert "secret" not in section
    assert "Runs with errors: 1." in folded
    assert "#### Benchmark" in folded
    assert not re.search(r"^#{1,3} ", folded, re.MULTILINE)


@pytest.mark.parametrize(
    "text",
    [
        "see /home/someone/work/x.py",
        "see ~/work",
        "see https://example.test/x",
        "mail someone@example.test",
        "host 10.1.2.3",
        "role arn:aws:iam::1:role/x",
        *(f"run on {own}" for own in sorted(telemetry.own_identities())),
    ],
)
def test_leaks_flags_local_and_internal_looking_values(text: str) -> None:
    assert pr.leaks(text)


@pytest.fixture
def pull_request(tmp_path: Path) -> Iterator[MagicMock]:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "pr.md").write_text(pr.section(public_report()))
    with (
        patch.object(github_api, "base_repo", return_value=("acme", "tools")),
        patch.object(contribute, "pr_title_body", return_value=("feat: x", BODY)),
        patch.object(contribute, "edit_pr") as edit,
    ):
        yield edit


def attach(tmp_path: Path, target: str, apply: bool) -> int:
    return pr.attach(target, tmp_path / "run", tmp_path, apply)


def test_attach_edits_the_pull_request_only_with_apply(
    tmp_path: Path, pull_request: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    target = "https://github.com/acme/tools/pull/7"

    assert attach(tmp_path, target, apply=False) == 0
    printed = capsys.readouterr().out
    pull_request.assert_not_called()
    assert "## Benchmark" in printed
    assert "7" in printed

    assert attach(tmp_path, "7", apply=True) == 0
    pull_request.assert_called_once()
    _, number, title, body = pull_request.call_args.args
    assert (number, title) == (7, "feat: x")
    assert body == pr.with_section(BODY, (tmp_path / "run" / "pr.md").read_text())


@pytest.mark.parametrize(
    ("pr_md", "target"),
    [
        ("## Benchmark\n\nSee /home/someone/x.\n", "7"),
        (None, "7"),
        ("## Benchmark\n", "https://github.com/other/repo/pull/7"),
        ("## Benchmark\n", "not-a-pr"),
    ],
)
def test_attach_refuses_a_leaking_missing_or_foreign_target(
    tmp_path: Path, pull_request: MagicMock, pr_md: str | None, target: str
) -> None:
    (tmp_path / "run" / "pr.md").unlink()
    if pr_md:
        (tmp_path / "run" / "pr.md").write_text(pr_md)

    assert attach(tmp_path, target, apply=True) == 2
    pull_request.assert_not_called()


def test_attach_reports_a_failed_edit(
    tmp_path: Path, pull_request: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    pull_request.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="no access\nmore"
    )

    assert attach(tmp_path, "7", apply=True) == 2
    assert capsys.readouterr().err == "no access\n"
