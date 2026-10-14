"""Tests that delegate agents cannot call mutating mcp-memory tools."""

from __future__ import annotations

import re

import pytest

from llm_prompts.install import prompts_dir

MUTATING_MEMORY_TOOLS = {
    f"mcp__memory__{name}"
    for name in (
        "create_entities",
        "create_relations",
        "delete_entity",
        "delete_relation",
        "delete_project",
        "add_observations",
        "delete_observations",
        "edit_observation",
        "set_entity_status",
        "set_metadata",
        "move_project_entities",
        "merge_entities",
        "merge_observations",
        "restore_entity",
        "trim_observations_to_outcome",
        "rename_entity",
        "move_entity_cross_scope",
        "vote",
    )
}


@pytest.mark.parametrize("agent", ["surveyor", "worker", "reasoner", "reviewer"])
def test_delegate_agent_denies_mutating_memory_tools(agent: str) -> None:
    """Each delegate agent lists every mutating memory tool in disallowedTools."""
    frontmatter = (
        next(prompts_dir("llm_prompts").glob(f"*/agents/{agent}.md"))
        .read_text()
        .split("---")[1]
    )
    assert set(re.findall(r"mcp__memory__\w+", frontmatter)) == MUTATING_MEMORY_TOOLS
