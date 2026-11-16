"""Rule and skill text for pi, whose delegates are pi-context forks."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_prompts.install import _requirements_met
from llm_prompts.render_template import (
    load_vars,
    parse_frontmatter,
    substitute_variables,
)

PROMPTS = Path(__file__).parent.parent / "src/llm_prompts/prompts"


def render_for_pi(source: str) -> str:
    """Render a prompt source for pi."""
    variables = {**load_vars(PROMPTS / "pi/vars.json"), "AGENT": "pi"}
    body, _ = parse_frontmatter((PROMPTS / source).read_text(encoding="utf-8"))
    return substitute_variables(body, variables)


def test_agent_teams_rule_is_not_installed_for_pi() -> None:
    _, declared = parse_frontmatter(
        (PROMPTS / "shared/rules/agent-teams.md").read_text(encoding="utf-8")
    )

    assert not _requirements_met(declared, "pi")


@pytest.mark.parametrize(
    ("source", "wording"),
    [
        ("rules/delegation.md", "A `reader` (default) only reads."),
        ("rules/delegation.md", "starts with an empty session"),
        ("rules/planning.md", "to `fork` readers"),
        ("rules/local-before-remote.md", "parallel `fork`s"),
        ("rules/anti-yap.md", "The `fork` tool shows main only that line"),
        ("skills/handoff/SKILL.md", "every `fork` worktree not yet landed"),
        ("skills/pickup/SKILL.md", "a subagent spawn (`fork`)"),
        ("skills/refine-plan/SKILL.md", "validation cold worker (`fork` with `model`)"),
        ("skills/eagle-vision/SKILL.md", "one cold-worker `fork` per node"),
    ],
)
def test_pi_rules_delegate_to_forks(
    monkeypatch: pytest.MonkeyPatch, source: str, wording: str
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    assert wording in render_for_pi(f"shared/{source}")


@pytest.mark.parametrize(
    ("source", "absent"),
    [
        ("rules/delegation.md", "coordinator"),
        ("rules/delegation.md", "subagent_type"),
        ("rules/delegation.md", "pi -p"),
        ("rules/herdr.md", "## Feature worktrees"),
        ("rules/herdr.md", "pi-herdsman"),
    ],
)
def test_pi_rules_drop_agent_team_wording(source: str, absent: str) -> None:
    assert absent not in render_for_pi(f"shared/{source}")
