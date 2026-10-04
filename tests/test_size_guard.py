"""Tests for the size-guard skip-set derivation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_prompts.size_guard import (
    Artifact,
    CheckResult,
    Violation,
    ceiling_for,
    check,
    resolve_skip_set,
)
from llm_prompts.size_limits import (
    AGENT_DESCRIPTION_CHARS,
    COLLECTION_BYTES,
    COLLECTION_SCHEDULE,
    FINALS,
    FRONTMATTER_VALID,
    RULE_BYTES,
    RULE_LINES,
    SCHEDULES,
    SKILL_BODY_BYTES,
    SKILL_DESCRIPTION_CHARS,
    WORKFLOW_LINES,
    Schedule,
    ScheduleStep,
)


def _artifact(
    metric: str,
    dest_name: str = "x.md",
    value: int | bool = 1,
    allowance: int | None = None,
) -> Artifact:
    return Artifact(metric, "claude-code", dest_name, value, Path(dest_name), allowance)


class TestCeilingFor:
    def test_unscheduled_artifact_gets_its_final(self) -> None:
        assert ceiling_for(_artifact(RULE_LINES)) == FINALS[RULE_LINES]

    def test_schedule_step_lowers_the_ceiling_for_a_gated_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        schedule = Schedule(
            steps=(ScheduleStep("S1", 3_000, frozenset({"gated.md"})),),
            active_step="S1",
        )
        monkeypatch.setitem(SCHEDULES, RULE_BYTES, schedule)
        assert ceiling_for(_artifact(RULE_BYTES, "gated.md")) == 3_000
        assert ceiling_for(_artifact(RULE_BYTES, "other.md")) == FINALS[RULE_BYTES]

    def test_allowance_replaces_the_ceiling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        schedule = Schedule(
            steps=(ScheduleStep("S1", 3_000, frozenset({"gated.md"})),),
            active_step="S1",
        )
        monkeypatch.setitem(SCHEDULES, RULE_BYTES, schedule)
        assert ceiling_for(_artifact(RULE_BYTES, "gated.md", allowance=9_000)) == 9_000

    def test_bool_metric_has_no_ceiling(self) -> None:
        assert ceiling_for(_artifact(FRONTMATTER_VALID, value=True)) is None

    def test_collection_bytes_uses_the_active_collection_step(self) -> None:
        artifact = _artifact(COLLECTION_BYTES, "claude-code")
        assert ceiling_for(artifact) == COLLECTION_SCHEDULE.active_threshold()

    def test_collection_bytes_allowance_replaces_the_active_step(self) -> None:
        artifact = _artifact(COLLECTION_BYTES, "claude-code", allowance=777)
        assert ceiling_for(artifact) == 777


class TestResolveSkipSet:
    @pytest.mark.parametrize(
        ("metric", "source_path", "dest_name", "actual", "threshold"),
        [
            (RULE_BYTES, "rules/big.md", "big.md", 6_000, 5_000),
            (WORKFLOW_LINES, "workflows/big.md", "big.md", 250, 200),
            (SKILL_BODY_BYTES, "skills/big/SKILL.md", "big", 6_000, 5_000),
            (AGENT_DESCRIPTION_CHARS, "claude-code/agents/big.md", "big.md", 250, 200),
        ],
    )
    def test_over_limit_is_in_skip_set(
        self,
        metric: str,
        source_path: str,
        dest_name: str,
        actual: int,
        threshold: int,
    ) -> None:
        source = Path(source_path)
        violation = Violation(
            metric, "claude-code", dest_name, actual, threshold, source
        )
        skip_set, frozen_agents = resolve_skip_set([violation])
        assert skip_set == {"claude-code": frozenset({source.resolve()})}
        assert frozen_agents == frozenset()

    def test_prompt_failing_more_than_one_check_is_in_skip_set_once(self) -> None:
        source = Path("skills/big/SKILL.md")
        violations = [
            Violation(SKILL_BODY_BYTES, "claude-code", "big", 6_000, 5_000, source),
            Violation(SKILL_DESCRIPTION_CHARS, "claude-code", "big", 250, 200, source),
        ]
        skip_set, _ = resolve_skip_set(violations)
        assert skip_set == {"claude-code": frozenset({source.resolve()})}

    def test_violations_for_different_targets_stay_in_separate_skip_sets(
        self,
    ) -> None:
        source_a = Path("rules/a.md")
        source_b = Path("rules/b.md")
        violations = [
            Violation(RULE_BYTES, "claude-code", "a.md", 6_000, 5_000, source_a),
            Violation(RULE_BYTES, "copilot", "b.md", 6_000, 5_000, source_b),
        ]
        skip_set, _ = resolve_skip_set(violations)
        assert skip_set == {
            "claude-code": frozenset({source_a.resolve()}),
            "copilot": frozenset({source_b.resolve()}),
        }

    def test_collection_bytes_violation_puts_nothing_in_skip_set(self) -> None:
        source = Path("prompts")
        violation = Violation(
            COLLECTION_BYTES, "claude-code", "claude-code", 60_000, 50_000, source
        )
        skip_set, frozen_agents = resolve_skip_set([violation])
        assert skip_set == {}
        assert frozen_agents == frozenset({"claude-code"})

    def test_no_violations_gives_empty_skip_set(self) -> None:
        skip_set, frozen_agents = resolve_skip_set([])
        assert skip_set == {}
        assert frozen_agents == frozenset()


class TestVarsRoot:
    @staticmethod
    def _rule_bytes(result: CheckResult) -> int:
        (artifact,) = (a for a in result.artifacts if a.metric == RULE_BYTES)
        assert isinstance(artifact.value, int)
        return artifact.value

    @staticmethod
    def _rule_root(tmp_path: Path) -> Path:
        rules = tmp_path / "root" / "shared" / "rules"
        rules.mkdir(parents=True, exist_ok=True)
        (rules / "r.md").write_text("{{X}}\n")
        return tmp_path / "root"

    @staticmethod
    def _vars_root(tmp_path: Path, value: str) -> Path:
        vars_dir = tmp_path / "vars" / "claude-code"
        vars_dir.mkdir(parents=True, exist_ok=True)
        (vars_dir / "vars.json").write_text(json.dumps({"X": value}))
        return tmp_path / "vars"

    def test_vars_come_from_vars_root_when_given(self, tmp_path: Path) -> None:
        result = check(
            [self._rule_root(tmp_path)],
            ("claude-code",),
            vars_root=self._vars_root(tmp_path, "a" * 100),
        )
        assert self._rule_bytes(result) == 101

    def test_collection_total_follows_vars_root(self, tmp_path: Path) -> None:
        def collection_bytes(value: str) -> int:
            result = check(
                [self._rule_root(tmp_path)],
                ("claude-code",),
                vars_root=self._vars_root(tmp_path, value),
            )
            (artifact,) = (a for a in result.artifacts if a.metric == COLLECTION_BYTES)
            assert isinstance(artifact.value, int)
            return artifact.value

        assert collection_bytes("a" * 100) - collection_bytes("a") == 99
