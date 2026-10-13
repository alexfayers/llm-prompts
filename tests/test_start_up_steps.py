"""Tests that hook-driven agents get no start-up instructions."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_prompts.render_template import (
    load_vars,
    nested_frontmatter,
    substitute_variables,
)


class TestStartUpStepsAreHookDriven:
    SHARED = Path(__file__).parent.parent / "src/llm_prompts/prompts/shared"
    HOOK_DRIVEN = ("claude-code", "pi")
    OTHERS = ("kiro", "cline", "codex", "copilot", "antigravity")
    SESSION_START_STEPS = (
        "`HANDOFF.md` is in the workspace root",
        "`read_graph(project=",
        "unmerged local branches",
    )

    def _render(self, source: str, agent: str) -> str:
        variables = {
            **load_vars(self.SHARED.parent / agent / "vars.json"),
            "AGENT": agent,
        }
        return substitute_variables(
            (self.SHARED / source).read_text(encoding="utf-8"), variables
        )

    @pytest.mark.parametrize("agent", HOOK_DRIVEN)
    def test_hook_driven_agents_get_no_start_up_instructions(self, agent: str) -> None:
        rule = self._render("rules/002-skill-usage.md", agent)
        skill = self._render("skills/session-start/SKILL.md", agent)

        assert "first tool call" not in rule
        assert not any(step in skill for step in self.SESSION_START_STEPS)

    @pytest.mark.parametrize("agent", [*HOOK_DRIVEN, *OTHERS])
    def test_every_agent_keeps_the_subagent_ban(self, agent: str) -> None:
        rule = self._render("rules/002-skill-usage.md", agent)

        assert (
            "A subagent (started by another agent) MUST NOT run `session-start`."
            in rule
        )

    @pytest.mark.parametrize("agent", OTHERS)
    def test_other_agents_keep_the_start_up_instructions(self, agent: str) -> None:
        rule = self._render("rules/002-skill-usage.md", agent)
        skill = self._render("skills/session-start/SKILL.md", agent)

        assert "first tool call" in rule
        assert all(step in skill for step in self.SESSION_START_STEPS)

    @pytest.mark.parametrize("agent", [*HOOK_DRIVEN, *OTHERS])
    def test_session_start_skill_is_flagged_for_injection(self, agent: str) -> None:
        lines = (
            self._render("skills/session-start/SKILL.md", agent)
            .split("---\n")[1]
            .splitlines()
        )

        assert nested_frontmatter(lines, "metadata") == {"inject_at_start": "true"}
