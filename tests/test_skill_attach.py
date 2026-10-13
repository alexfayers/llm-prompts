"""Tests for the subagent skill suggestions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from cline_hooks.core.plugin import HookResult

from llm_prompts.skill_attach import SkillAttach

Spawn = Callable[..., HookResult]


@pytest.fixture
def spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Spawn:
    def run(
        flag: str, task: str, skills: str = "tdd", tool: str = "spawn_agent"
    ) -> HookResult:
        dirs = [tmp_path / name for name in skills.split()]
        for skill in dirs:
            skill.mkdir(exist_ok=True)
            (skill / "SKILL.md").write_text(f"---\nmetadata:\n  {flag}\n---\n")
        spec = SimpleNamespace(name="pi", skill_hint=lambda n: "HINT " + ",".join(n))
        monkeypatch.setattr(
            "llm_prompts.skill_attach.read_manifest",
            lambda: {"pi": {"files": [str(d) for d in dirs]}},
        )
        monkeypatch.setattr(
            "llm_prompts.skill_attach.get_protocol",
            lambda: SimpleNamespace(frontend_spec=spec),
        )
        params = {"task": task, "definition": "worker"}
        hook = SkillAttach().on_hook(
            "PreToolUse",
            logger=logging.getLogger("t"),
            tool_name=tool,
            parameters=params,
        )
        return hook or HookResult()

    return run


class TestSkillAttach:
    def test_a_trigger_match_appends_the_hint_to_the_task(self, spawn: Spawn) -> None:
        result = spawn("attach_triggers: tests, red-green", "Write tests")

        assert result.updated_input == {
            "task": "Write tests\n\nHINT tdd",
            "definition": "worker",
        }
        assert result.fallback_notes == ["HINT tdd"]

    def test_at_most_three_skills_and_none_the_task_names(self, spawn: Spawn) -> None:
        result = spawn("attach_triggers: tests", "Write tests, load e", "a b c d e")

        assert result.fallback_notes == ["HINT a,b,c"]

    def test_a_skill_attaches_to_the_agent_types_it_lists(self, spawn: Spawn) -> None:
        assert spawn("attach_roles: worker, tester", "Do it").fallback_notes == [
            "HINT tdd"
        ]

    def test_nothing_changes_for_other_tools_or_unmatched_tasks(
        self, spawn: Spawn
    ) -> None:
        assert (
            spawn("attach_triggers: tests", "Write tests", tool="read") == HookResult()
        )
        assert spawn("attach_triggers: tests", "Tidy the docs") == HookResult()
