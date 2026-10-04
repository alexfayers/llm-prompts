"""Tests for the prompt size report."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_prompts import size_report
from llm_prompts.size_guard import CHECKED_TARGETS, Artifact, CheckResult
from llm_prompts.size_limits import (
    COLLECTION_BYTES,
    FINALS,
    FRONTMATTER_VALID,
    RULE_BYTES,
    RULE_LINES,
)
from llm_prompts.size_report import Row, build_report, compare, render_markdown

BASE_ROOT = Path("/base/prompts")
HEAD_ROOT = Path("/head/prompts")


def _artifact(
    root: Path,
    value: int | bool,
    *,
    metric: str = RULE_BYTES,
    target: str = "claude-code",
    name: str = "a.md",
    allowance: int | None = None,
) -> Artifact:
    return Artifact(
        metric, target, name, value, root / "shared" / "rules" / name, allowance
    )


class TestCompare:
    def test_joins_base_and_head_on_metric_target_and_name(self) -> None:
        rows = compare(
            [_artifact(BASE_ROOT, 100)],
            [_artifact(HEAD_ROOT, 120)],
            [BASE_ROOT],
            [HEAD_ROOT],
        )
        assert rows == [
            Row(
                RULE_BYTES,
                ("claude-code",),
                "",
                "shared/rules/a.md",
                100,
                120,
                FINALS[RULE_BYTES],
            )
        ]

    def test_installed_names_matching_the_source_collapse_into_one_row(
        self,
    ) -> None:
        source = HEAD_ROOT / "shared" / "rules" / "a.md"
        head = [
            Artifact(RULE_BYTES, "copilot", "a.instructions.md", 120, source),
            Artifact(RULE_BYTES, "kiro", "a.md", 120, source),
        ]
        (row,) = compare([], head, [BASE_ROOT], [HEAD_ROOT])
        assert (row.targets, row.name) == (("copilot", "kiro"), "")

    def test_installed_name_differing_from_the_source_is_kept(self) -> None:
        source = HEAD_ROOT / "shared" / "agents" / "worker.md"
        head = [Artifact(RULE_BYTES, "kiro", "worker-sonnet-low.md", 120, source)]
        (row,) = compare([], head, [BASE_ROOT], [HEAD_ROOT])
        assert row.name == "worker-sonnet-low.md"

    def test_artifact_only_on_head_is_new(self) -> None:
        (row,) = compare([], [_artifact(HEAD_ROOT, 120)], [BASE_ROOT], [HEAD_ROOT])
        assert (row.base, row.head) == (None, 120)

    def test_artifact_only_on_base_is_removed(self) -> None:
        (row,) = compare([_artifact(BASE_ROOT, 100)], [], [BASE_ROOT], [HEAD_ROOT])
        assert (row.base, row.head, row.file) == (100, None, "shared/rules/a.md")
        assert row.ceiling == FINALS[RULE_BYTES]

    def test_bool_metrics_are_dropped(self) -> None:
        artifact = _artifact(HEAD_ROOT, True, metric=FRONTMATTER_VALID)
        assert compare([], [artifact], [BASE_ROOT], [HEAD_ROOT]) == []

    def test_targets_with_identical_values_collapse_into_one_row(self) -> None:
        head = [
            _artifact(HEAD_ROOT, 120, target="claude-code"),
            _artifact(HEAD_ROOT, 120, target="kiro"),
            _artifact(HEAD_ROOT, 130, target="copilot"),
        ]
        rows = compare([], head, [BASE_ROOT], [HEAD_ROOT])
        assert [row.targets for row in rows] == [
            ("claude-code", "kiro"),
            ("copilot",),
        ]

    def test_overlay_sources_are_prefixed_with_their_directory(self) -> None:
        overlay = Path("/work/team-overlay/prompts")
        rows = compare(
            [],
            [_artifact(overlay, 10)],
            [BASE_ROOT, overlay],
            [HEAD_ROOT, overlay],
        )
        assert rows[0].file == "team-overlay:shared/rules/a.md"


def _row(base: int | None, head: int | None, ceiling: int | None = 5_000) -> Row:
    return Row(
        RULE_BYTES, ("claude-code",), "", "shared/rules/a.md", base, head, ceiling
    )


class TestRow:
    def test_delta_is_head_minus_base(self) -> None:
        assert _row(100, 120).delta == 20

    def test_delta_of_new_and_removed_rows_counts_the_missing_side_as_zero(
        self,
    ) -> None:
        assert (_row(None, 120).delta, _row(100, None).delta) == (120, -100)

    def test_pct_is_delta_over_base(self) -> None:
        assert _row(200, 210).pct == 5.0

    def test_pct_is_none_without_both_sides(self) -> None:
        assert (_row(None, 120).pct, _row(100, None).pct, _row(0, 5).pct) == (
            None,
            None,
            None,
        )

    def test_over_when_head_exceeds_ceiling(self) -> None:
        assert (_row(1, 5_001).over, _row(1, 5_000).over) == (True, False)

    def test_not_over_without_head_or_ceiling(self) -> None:
        assert (_row(1, None).over, _row(1, 9_999, None).over) == (False, False)


def _collection(base: int, head: int, *targets: str) -> Row:
    return Row(COLLECTION_BYTES, targets, targets[0], "-", base, head, 50_000)


class TestRenderMarkdown:
    def test_tiny_change_badge_is_url_encoded(self) -> None:
        report = render_markdown([_collection(100_000, 99_996, "kiro")])
        assert "https://img.shields.io/badge/kiro-%3C0.1%25-brightgreen" in report

    def test_without_changes_shows_only_badges_headline_and_notice(self) -> None:
        report = render_markdown([_collection(100, 100, "claude-code")])
        assert report == (
            "![claude-code](https://img.shields.io/badge/claude--code-0%25-lightgrey)"
            "\n\n**Prompt size** &#x26AA; 0 files changed size in this PR, "
            "0 over the limit\n\nThis PR changes no prompt sizes.\n"
        )

    def test_headline_counts_changed_and_over_files_and_colours_by_summed_delta(
        self,
    ) -> None:
        collection = _collection(100, 110, "claude-code", "kiro")
        a_lines = Row(
            RULE_LINES, ("claude-code",), "", "shared/rules/a.md", 10, 12, 200
        )
        b_bytes = Row(
            RULE_BYTES, ("claude-code",), "", "shared/rules/b.md", 1, 5_001, 5_000
        )
        larger = render_markdown([collection, _row(100, 110), a_lines, b_bytes])
        smaller = render_markdown([collection, _row(110, 100), a_lines])
        assert (
            "**Prompt size** &#x1F534; 2 files changed size in this PR, "
            "1 over the limit"
        ) in larger
        assert (
            "**Prompt size** &#x1F7E2; 1 file changed size in this PR, 0 over the limit"
        ) in smaller

    def test_file_shows_the_source_path_without_shared_or_installed_name(
        self,
    ) -> None:
        def row(name: str, file: str) -> Row:
            return Row(RULE_BYTES, ("kiro",), name, file, 1, 2, 5_000)

        report = render_markdown(
            [
                row("", "kiro/rules/only.md"),
                row("", "team-overlay:shared/rules/a.md"),
                row("worker-sonnet-low.md", "shared/agents/worker.md"),
            ]
        )
        assert "| kiro/rules/only.md |" in report
        assert "| team-overlay:rules/a.md |" in report
        assert "| agents/worker.md (worker-sonnet-low.md) |" in report

    def test_badges_show_each_targets_change_coloured_by_direction(self) -> None:
        report = render_markdown(
            [
                _collection(100, 110, "claude-code", "kiro"),
                _collection(100, 90, "copilot"),
                _collection(100, 100, "cline"),
                _row(1, 2),
            ]
        )
        badges = report.split("\n\n")[0]
        assert badges == (
            "![claude-code](https://img.shields.io/badge/claude--code-%2B10.0%25-red)"
            " ![kiro](https://img.shields.io/badge/kiro-%2B10.0%25-red)"
            " ![copilot](https://img.shields.io/badge/copilot---10.0%25-brightgreen)"
            " ![cline](https://img.shields.io/badge/cline-0%25-lightgrey)"
        )

    def test_collection_table_lists_each_target(self) -> None:
        report = render_markdown(
            [
                _collection(100, 110, "claude-code", "kiro"),
                _collection(5, 6, "copilot"),
                _row(1, 2),
            ]
        )
        assert "| | target | before | after | change | % | limit |" in report
        assert "| :-: | --- | ---: | ---: | ---: | ---: | ---: |" in report
        assert (
            "| &#x1F534; | claude-code | 100 | 110 | +10 | +10.0% | 50,000 |" in report
        )
        assert "| &#x1F534; | kiro | 100 | 110 | +10 | +10.0% | 50,000 |" in report
        assert "| &#x1F534; | copilot | 5 | 6 | +1 | +20.0% | 50,000 |" in report

    def test_collection_table_sits_in_a_per_agent_details_block(self) -> None:
        report = render_markdown([_collection(100, 110, "kiro"), _row(1, 2)])
        per_agent = report.split("<details>")[1]
        assert per_agent.startswith("\n<summary>Per-agent impact</summary>\n\n")
        assert "| | target | before | after | change | % | limit |" in per_agent
        assert "| target |" not in report.split("<details>")[0]

    def test_zero_and_tiny_changes_show_no_signed_zero(self) -> None:
        report = render_markdown(
            [
                _collection(100, 100, "claude-code"),
                _collection(100_000, 99_996, "kiro"),
                _row(1, 2),
            ]
        )
        assert "| &#x26AA; | claude-code | 100 | 100 | 0 | 0% | 50,000 |" in report
        assert (
            "| &#x26A0;&#xFE0F; | kiro | 100,000 | 99,996 | -4 | <0.1% | 50,000 |"
            in report
        )

    def test_changed_rows_show_above_the_details_blocks_sorted_by_absolute_delta(
        self,
    ) -> None:
        rows = [
            _row(100, 110),
            Row(RULE_BYTES, ("kiro",), "", "shared/rules/big.md", 900, 500, 5_000),
            Row(RULE_BYTES, ("kiro",), "", "shared/rules/same.md", 7, 7, 5_000),
        ]
        changed = render_markdown(rows).split("<details>")[0]
        assert (
            "| | file | metric | targets | before | after | change | % | limit |"
            in changed
        )
        assert "| :-: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |" in changed
        assert changed.index("big.md") < changed.index("rules/a.md")
        assert "same.md" not in changed
        assert (
            "| &#x1F7E2; | rules/big.md | rule_bytes | kiro | 900 | 500 | -400 | -44.4% | 5,000 |"
            in changed
        )

    def test_all_checked_targets_render_as_all(self) -> None:
        row = Row(RULE_BYTES, CHECKED_TARGETS, "", "shared/rules/a.md", 1, 2, 5_000)
        assert "| rule_bytes | all |" in render_markdown([row])

    def test_new_and_removed_rows_show_a_dash_and_blank_change(self) -> None:
        report = render_markdown([_row(None, 50), _row(40, None)])
        assert (
            "| &#x1F195; | rules/a.md | rule_bytes | claude-code | - | 50 | | | 5,000 |"
            in report
        )
        assert (
            "| &#x1F5D1;&#xFE0F; | rules/a.md | rule_bytes | claude-code | 40 | - | | | 5,000 |"
            in report
        )

    def test_row_over_its_limit_gets_the_over_limit_emoji(self) -> None:
        assert (
            "| &#x26A0;&#xFE0F; | rules/a.md | rule_bytes | claude-code | 1 | 5,001 | +5,000 | +500000.0% | 5,000 |"
            in render_markdown([_row(1, 5_001)])
        )

    def test_all_rows_block_holds_every_row_including_collection(self) -> None:
        rows = [
            _collection(100, 110, "kiro"),
            _row(100, 110),
            Row(RULE_BYTES, ("kiro",), "", "shared/rules/same.md", 7, 7, 5_000),
        ]
        details = render_markdown(rows).split("<details>")[2]
        assert details.startswith("\n<summary>All rows</summary>\n\n")
        assert "same.md" in details
        assert "| rules/a.md |" in details
        assert "| - | collection_bytes | kiro |" in details
        assert details.rstrip().endswith("</details>")


class TestBuildReport:
    def test_missing_base_says_there_is_nothing_to_compare(
        self, tmp_path: Path
    ) -> None:
        report = build_report(tmp_path / "missing")
        assert report.startswith("## Prompt size report")
        assert "No base" in report

    def test_measures_base_with_its_own_variables_and_head_overlays(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        overlay = Path("/work/overlay/prompts")
        monkeypatch.setattr(
            size_report, "_size_guard_roots", lambda: [HEAD_ROOT, overlay]
        )
        calls: list[tuple[list[Path], Path | None]] = []

        def fake_check(
            roots: list[Path], *, vars_root: Path | None = None
        ) -> CheckResult:
            calls.append((roots, vars_root))
            value = 100 if vars_root else 120
            return CheckResult(True, [_artifact(roots[0], value)], [], "")

        monkeypatch.setattr(size_report, "check", fake_check)
        report = build_report(tmp_path)
        assert calls == [([HEAD_ROOT, overlay], None), ([tmp_path, overlay], tmp_path)]
        assert "| rules/a.md | rule_bytes | claude-code | 100 | 120 | +20 |" in report
