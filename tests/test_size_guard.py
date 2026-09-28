"""Tests for the size-guard skip-set derivation."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_prompts.size_guard import Violation, resolve_skip_set
from llm_prompts.size_limits import (
    AGENT_DESCRIPTION_CHARS,
    COLLECTION_BYTES,
    RULE_BYTES,
    SKILL_BODY_BYTES,
    SKILL_DESCRIPTION_CHARS,
    WORKFLOW_LINES,
)


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
