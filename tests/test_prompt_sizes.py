"""Tests for the prompt-size guard: thresholds/schedules and measurement."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.render_template import resolve_frontmatter, split_frontmatter
from llm_prompts.size_guard import (
    Artifact,
    Violation,
    check,
    evaluate,
    format_report,
    iter_artifacts,
    parked_state_lines,
)
from llm_prompts.size_limits import (
    AGENT_BASE_DESCRIPTION_MAX_CHARS,
    AGENT_DESCRIPTION_CHARS,
    CORPUS_SCHEDULE,
    FINALS,
    FRONTMATTER_VALID,
    NO_UNSUBSTITUTED_PLACEHOLDERS,
    RULE_BYTES,
    RULE_LINES,
    SCHEDULES,
    SKILL_BODY_BYTES,
    SKILL_DESCRIPTION_CHARS,
    UNITS,
    WORKFLOW_BYTES,
    WORKFLOW_LINES,
    CorpusSchedule,
    CorpusStep,
    Schedule,
    ScheduleStep,
)


class TestFinalsAndUnits:
    def test_every_numeric_metric_has_a_final(self) -> None:
        for metric in (
            RULE_LINES,
            RULE_BYTES,
            SKILL_BODY_BYTES,
            WORKFLOW_BYTES,
            WORKFLOW_LINES,
            SKILL_DESCRIPTION_CHARS,
            AGENT_DESCRIPTION_CHARS,
        ):
            assert metric in FINALS
            assert metric in UNITS

    def test_agent_base_description_budget_derived_from_suffix(self) -> None:
        # 200 - len(" [sonnet, medium effort]") == 176, the longest real
        # model/effort combination `_apply_variant_frontmatter` can append.
        assert AGENT_BASE_DESCRIPTION_MAX_CHARS == 176


class TestResolveFrontmatter:
    def test_plain_single_line_values_pass_through(self) -> None:
        lines, _ = split_frontmatter("---\nname: worker\ndescription: A thing\n---\n")
        assert resolve_frontmatter(lines) == {
            "name": "worker",
            "description": "A thing",
        }

    def test_folds_block_scalar_with_spaces(self) -> None:
        content = "---\ndescription: >-\n  First line.\n  Second line.\n---\n"
        lines, _ = split_frontmatter(content)
        assert resolve_frontmatter(lines) == {"description": "First line. Second line."}

    def test_literal_block_scalar_keeps_newlines(self) -> None:
        content = "---\nnotes: |\n  First line.\n  Second line.\n---\n"
        lines, _ = split_frontmatter(content)
        assert resolve_frontmatter(lines) == {"notes": "First line.\nSecond line."}

    def test_block_scalar_followed_by_another_key(self) -> None:
        content = "---\ndescription: >-\n  Folded text.\ndisallowedTools: Agent\n---\n"
        lines, _ = split_frontmatter(content)
        assert resolve_frontmatter(lines) == {
            "description": "Folded text.",
            "disallowedTools": "Agent",
        }

    def test_folded_description_matches_real_yaml_parsing(self) -> None:
        import yaml

        content = (
            "---\n"
            "name: architect\n"
            "description: >-\n"
            "  Opus sub-lead for the pipeline described in agent-teams.md.\n"
            "  Reach for this subagent type when a task needs research, then\n"
            "  design, then several independent edits.\n"
            "disallowedTools: Agent\n"
            "---\n"
        )
        lines, _ = split_frontmatter(content)
        resolved = resolve_frontmatter(lines)
        assert resolved is not None
        assert (
            resolved["description"] == yaml.safe_load("\n".join(lines))["description"]
        )

    def test_corrupted_indicator_with_trailing_suffix_is_malformed(self) -> None:
        lines = [
            "description: >- [opus, medium effort]",
            "  Body line.",
        ]
        assert resolve_frontmatter(lines) is None


class TestScheduleStepLookup:
    def test_returns_none_when_schedule_not_engaged(self) -> None:
        schedule = Schedule(
            steps=(ScheduleStep("W2", 100, frozenset({"a.md"})),),
        )
        assert schedule.active_threshold_for("a.md") is None

    def test_returns_threshold_for_gated_name(self) -> None:
        schedule = Schedule(
            steps=(ScheduleStep("W2", 100, frozenset({"a.md"})),),
            active_step="W2",
        )
        assert schedule.active_threshold_for("a.md") == 100

    def test_returns_none_for_ungated_name(self) -> None:
        schedule = Schedule(
            steps=(ScheduleStep("W2", 100, frozenset({"a.md"})),),
            active_step="W2",
        )
        assert schedule.active_threshold_for("b.md") is None

    def test_returns_none_when_active_step_gates_a_different_name_only(
        self,
    ) -> None:
        schedule = Schedule(
            steps=(
                ScheduleStep("W2", 100, frozenset({"a.md"})),
                ScheduleStep("W3", 50, frozenset({"b.md"})),
            ),
            active_step="W2",
        )
        assert schedule.active_threshold_for("b.md") is None


class TestScheduleAllowsMultiStepMembership:
    def test_a_name_can_appear_in_more_than_one_step(self) -> None:
        schedule = SCHEDULES[RULE_BYTES]
        names_by_step = {step.name: step.files for step in schedule.steps}
        multi_step_names = {
            name
            for name in frozenset.union(*names_by_step.values())
            if sum(name in files for files in names_by_step.values()) > 1
        }
        assert multi_step_names, "expected at least one multi-step artifact"

    def test_coding_and_memory_each_need_more_than_one_pass(self) -> None:
        schedule = SCHEDULES[RULE_BYTES]
        for name in ("coding.md", "memory.md"):
            step_count = sum(name in step.files for step in schedule.steps)
            assert step_count > 1, f"{name} should appear in more than one step"


class TestCorpusSchedule:
    def test_active_threshold_returns_active_step_value(self) -> None:
        schedule = CorpusSchedule(
            steps=(CorpusStep("open", 200), CorpusStep("W1", 100)),
            active_step="open",
        )
        assert schedule.active_threshold() == 200

    def test_unknown_active_step_raises(self) -> None:
        schedule = CorpusSchedule(
            steps=(CorpusStep("open", 200),), active_step="missing"
        )
        with pytest.raises(KeyError):
            schedule.active_threshold()

    def test_module_corpus_schedule_active_step_is_a_known_step(self) -> None:
        assert CORPUS_SCHEDULE.active_threshold() == 425_000


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_prompts_tree(
    root: Path, *, targets: tuple[str, ...] = ("claude-code",)
) -> None:
    """Build a minimal synthetic prompts tree exercising every artifact kind."""
    for target in targets:
        _write(root / target / "vars.json", json.dumps({"AGENT": target}))

    _write(
        root / "shared" / "rules" / "shared-rule.md",
        "# Shared rule\n\nUses {{AGENT}} here.\n",
    )
    _write(
        root / "claude-code" / "rules" / "agent-only.md",
        "# Agent-only rule\n\nCarried through verbatim.\n",
    )
    _write(
        root / "shared" / "workflows" / "flow.md",
        "# Flow\n\nDoes a thing.\n",
    )
    _write(
        root / "shared" / "skills" / "demo" / "SKILL.md",
        "---\nname: demo\ndescription: A demo skill.\n---\n\nFor {{AGENT}}.\n",
    )
    _write(
        root / "claude-code" / "agents" / "worker.md",
        "---\nname: worker\ndescription: Does mechanical things.\n"
        "generate_variants: sonnet-low\n---\n\nBody.\n",
    )
    _write(
        root / "claude-code" / "agents" / "plain.md",
        "---\nname: plain\ndescription: A plain agent.\n---\n\nBody.\n",
    )


class TestIterArtifactsDispatch:
    def test_shared_rule_is_rendered_agent_specific_rule_is_linked(
        self, tmp_path: Path
    ) -> None:
        _make_prompts_tree(tmp_path)

        with patch("llm_prompts.size_guard._own_root_dir", return_value=tmp_path):
            artifacts = list(iter_artifacts([tmp_path], targets=("claude-code",)))

        by_name = {a.dest_name: a for a in artifacts if a.metric == RULE_BYTES}
        shared_content = "# Shared rule\n\nUses claude-code here.\n"
        agent_content = "# Agent-only rule\n\nCarried through verbatim.\n"
        assert by_name["shared-rule.md"].value == len(shared_content.encode())
        assert by_name["agent-only.md"].value == len(agent_content.encode())

    def test_skill_description_and_body_measured_after_substitution(
        self, tmp_path: Path
    ) -> None:
        _make_prompts_tree(tmp_path)

        with patch("llm_prompts.size_guard._own_root_dir", return_value=tmp_path):
            artifacts = list(iter_artifacts([tmp_path], targets=("claude-code",)))

        desc = next(
            a
            for a in artifacts
            if a.metric == SKILL_DESCRIPTION_CHARS and a.dest_name == "demo"
        )
        assert desc.value == len("A demo skill.")
        body = next(
            a
            for a in artifacts
            if a.metric == SKILL_BODY_BYTES and a.dest_name == "demo"
        )
        assert body.value == len(b"For claude-code.\n")

    def test_generated_variant_and_plain_agent_both_measured(
        self, tmp_path: Path
    ) -> None:
        _make_prompts_tree(tmp_path)

        with patch("llm_prompts.size_guard._own_root_dir", return_value=tmp_path):
            artifacts = list(iter_artifacts([tmp_path], targets=("claude-code",)))

        agent_names = {
            a.dest_name for a in artifacts if a.metric == AGENT_DESCRIPTION_CHARS
        }
        assert "worker-sonnet-low.md" in agent_names
        assert "plain.md" in agent_names
        assert "worker.md" not in agent_names

    def test_frontmatter_and_placeholder_checks_pass_for_clean_content(
        self, tmp_path: Path
    ) -> None:
        _make_prompts_tree(tmp_path)

        with patch("llm_prompts.size_guard._own_root_dir", return_value=tmp_path):
            artifacts = list(iter_artifacts([tmp_path], targets=("claude-code",)))

        assert all(
            a.value is True
            for a in artifacts
            if a.metric in (FRONTMATTER_VALID, NO_UNSUBSTITUTED_PLACEHOLDERS)
        )

    def test_agent_specific_placeholder_leak_fails_no_unsubstituted_placeholders(
        self, tmp_path: Path
    ) -> None:
        _make_prompts_tree(tmp_path)
        _write(
            tmp_path / "claude-code" / "rules" / "agent-only.md",
            "# Agent-only rule\n\nNever substituted: {{AGENT}}.\n",
        )

        with patch("llm_prompts.size_guard._own_root_dir", return_value=tmp_path):
            artifacts = list(iter_artifacts([tmp_path], targets=("claude-code",)))

        leaked = [
            a
            for a in artifacts
            if a.metric == NO_UNSUBSTITUTED_PLACEHOLDERS
            and a.dest_name == "agent-only.md"
        ]
        assert leaked == [
            Artifact(
                NO_UNSUBSTITUTED_PLACEHOLDERS,
                "claude-code",
                "agent-only.md",
                False,
                leaked[0].source,
            )
        ]

    def test_copilot_dest_name_gets_instructions_suffix(self, tmp_path: Path) -> None:
        _make_prompts_tree(tmp_path, targets=("copilot",))

        with patch("llm_prompts.size_guard._own_root_dir", return_value=tmp_path):
            names = {
                a.dest_name
                for a in iter_artifacts([tmp_path], targets=("copilot",))
                if a.metric == RULE_BYTES
            }

        assert "shared-rule.instructions.md" in names
        assert "shared-rule.md" not in names

    def test_workflow_bytes_and_lines_measured(self, tmp_path: Path) -> None:
        _make_prompts_tree(tmp_path)

        with patch("llm_prompts.size_guard._own_root_dir", return_value=tmp_path):
            artifacts = list(iter_artifacts([tmp_path], targets=("claude-code",)))

        flow_bytes = next(
            a
            for a in artifacts
            if a.metric == WORKFLOW_BYTES and a.dest_name == "flow.md"
        )
        flow_lines = next(
            a
            for a in artifacts
            if a.metric == WORKFLOW_LINES and a.dest_name == "flow.md"
        )
        content = "# Flow\n\nDoes a thing.\n"
        assert flow_bytes.value == len(content.encode())
        assert flow_lines.value == len(content.splitlines())

    def test_scanning_multiple_roots_combines_their_artifacts(
        self, tmp_path: Path
    ) -> None:
        own_root = tmp_path / "own"
        first = tmp_path / "first"
        second = tmp_path / "second"
        _write(own_root / "claude-code" / "vars.json", json.dumps({"AGENT": "x"}))
        _write(first / "shared" / "rules" / "one.md", "# One\n")
        _write(second / "shared" / "rules" / "two.md", "# Two\n")

        with patch("llm_prompts.size_guard._own_root_dir", return_value=own_root):
            names = {
                a.dest_name
                for a in iter_artifacts([first, second], targets=("claude-code",))
                if a.metric == RULE_BYTES
            }

        assert names == {"one.md", "two.md"}


class TestEvaluate:
    def test_artifact_within_final_passes(self) -> None:
        artifact = Artifact(RULE_BYTES, "claude-code", "ok.md", 5_000, Path("ok.md"))
        assert evaluate([artifact]) == []

    def test_artifact_exceeding_final_fails(self) -> None:
        artifact = Artifact(RULE_BYTES, "claude-code", "big.md", 5_001, Path("big.md"))
        violations = evaluate([artifact])
        assert violations == [
            Violation(RULE_BYTES, "claude-code", "big.md", 5_001, 5_000, Path("big.md"))
        ]

    def test_active_schedule_step_tightens_the_final(self) -> None:
        artifact = Artifact(RULE_BYTES, "claude-code", "a.md", 4_500, Path("a.md"))
        schedule = Schedule(
            steps=(ScheduleStep("W2", 4_000, frozenset({"a.md"})),),
            active_step="W2",
        )
        with patch.dict(SCHEDULES, {RULE_BYTES: schedule}):
            violations = evaluate([artifact])
        assert violations == [
            Violation(RULE_BYTES, "claude-code", "a.md", 4_500, 4_000, Path("a.md"))
        ]

    def test_bool_metric_false_is_a_violation(self) -> None:
        artifact = Artifact(
            FRONTMATTER_VALID, "claude-code", "bad.md", False, Path("bad.md")
        )
        violations = evaluate([artifact])
        assert violations == [
            Violation(
                FRONTMATTER_VALID, "claude-code", "bad.md", False, True, Path("bad.md")
            )
        ]

    def test_bool_metric_true_passes(self) -> None:
        artifact = Artifact(
            FRONTMATTER_VALID, "claude-code", "ok.md", True, Path("ok.md")
        )
        assert evaluate([artifact]) == []


class TestFormatReport:
    def test_no_violations_reports_pass(self) -> None:
        assert format_report([]) == "All prompt-size checks passed."

    def test_violation_names_file_metric_actual_and_threshold(self) -> None:
        violation = Violation(
            RULE_BYTES, "claude-code", "big.md", 6_000, 5_000, Path("big.md")
        )
        report = format_report([violation])
        assert "big.md" in report
        assert "claude-code" in report
        assert "6000" in report
        assert "5000" in report
        assert UNITS[RULE_BYTES] in report


class TestCheck:
    def test_reports_no_violations_for_clean_synthetic_tree(
        self, tmp_path: Path
    ) -> None:
        _make_prompts_tree(tmp_path)

        with patch("llm_prompts.size_guard._own_root_dir", return_value=tmp_path):
            result = check([tmp_path], targets=("claude-code",))

        assert result.passed is True
        assert result.violations == []
        assert result.report == "All prompt-size checks passed."

    def test_oversized_artifact_fails_with_a_readable_report(
        self, tmp_path: Path
    ) -> None:
        _make_prompts_tree(tmp_path)
        _write(
            tmp_path / "shared" / "rules" / "shared-rule.md",
            "# Shared rule\n\n" + ("x " * FINALS[RULE_BYTES]),
        )

        with patch("llm_prompts.size_guard._own_root_dir", return_value=tmp_path):
            result = check([tmp_path], targets=("claude-code",))

        assert result.passed is False
        assert any(
            v.metric == RULE_BYTES and v.dest_name == "shared-rule.md"
            for v in result.violations
        )
        assert "shared-rule.md" in result.report
        assert "compress, don't split" in result.report

    def test_scoping_roots_to_one_overlay_measures_only_its_files(
        self, tmp_path: Path
    ) -> None:
        own_root = tmp_path / "own"
        overlay_root = tmp_path / "overlay"
        _write(own_root / "claude-code" / "vars.json", json.dumps({"AGENT": "x"}))
        _write(own_root / "shared" / "rules" / "own.md", "# Own\n")
        _write(overlay_root / "shared" / "rules" / "overlay.md", "# Overlay\n")

        with patch("llm_prompts.size_guard._own_root_dir", return_value=own_root):
            names = {
                a.dest_name
                for a in iter_artifacts([overlay_root], targets=("claude-code",))
                if a.metric == RULE_BYTES
            }

        assert names == {"overlay.md"}


class TestParkedStateLines:
    def test_no_artifacts_over_final_reports_nothing(self) -> None:
        artifact = Artifact(RULE_BYTES, "claude-code", "a.md", 10, Path("a.md"))
        assert parked_state_lines([artifact]) == []

    def test_over_final_artifacts_grouped_by_metric(self) -> None:
        final = FINALS[RULE_BYTES]
        artifacts = [
            Artifact(RULE_BYTES, "claude-code", "a.md", final + 100, Path("a.md")),
            Artifact(RULE_BYTES, "claude-code", "b.md", final + 5_000, Path("b.md")),
        ]
        lines = parked_state_lines(artifacts)
        assert len(lines) == 1
        assert f"current {final + 5_000:,}" in lines[0]
        assert f"final {final:,}" in lines[0]
        assert "2 files awaiting compression" in lines[0]


class TestNoOwnedTemplateUsesRepoRoot:
    """REPO_ROOT resolves to an absolute, machine-specific path. If any owned
    template used it, rendered content - and the measurements checked against
    it - would differ by machine."""

    def test_no_md_file_references_repo_root(self) -> None:
        from importlib.resources import files

        root = Path(str(files("llm_prompts") / "prompts"))
        offenders = [
            path
            for path in root.rglob("*.md")
            if "REPO_ROOT" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []
