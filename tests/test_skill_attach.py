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
    def run(skills: dict[str, str], task: str, tool: str = "spawn_agent") -> HookResult:
        for name, metadata in skills.items():
            (tmp_path / name).mkdir(exist_ok=True)
            (tmp_path / name / "SKILL.md").write_text(
                f"---\nmetadata:\n{metadata}---\n"
            )
        files = {"pi": {"files": [str(tmp_path / name) for name in skills]}}
        hint = SimpleNamespace(
            name="pi", skill_hint=lambda names: "HINT " + ",".join(names)
        )
        monkeypatch.setattr("llm_prompts.skill_attach.read_manifest", lambda: files)
        monkeypatch.setattr(
            "llm_prompts.skill_attach.get_protocol",
            lambda: SimpleNamespace(frontend_spec=hint),
        )
        return (
            SkillAttach().on_hook(
                "PreToolUse",
                logger=logging.getLogger("test"),
                tool_name=tool,
                parameters={"task": task, "definition": "worker"},
            )
            or HookResult()
        )

    return run


class TestSkillAttach:
    def test_a_spawn_matching_a_trigger_gets_the_hint_appended_to_its_task(
        self, spawn: Spawn
    ) -> None:
        result = spawn({"tdd": "  attach_triggers: tests, red-green\n"}, "Write tests")

        assert result.updated_input == {
            "task": "Write tests\n\nHINT tdd",
            "definition": "worker",
        }
        assert result.fallback_notes == ["HINT tdd"]

    def test_at_most_three_skills_are_suggested_and_none_the_task_already_names(
        self, spawn: Spawn
    ) -> None:
        skills = {n: "  attach_triggers: tests\n" for n in ("a", "b", "c", "d", "e")}

        result = spawn(skills, "Write tests, load skill e")

        assert result.fallback_notes == ["HINT a,b,c"]

    def test_a_skill_attaches_to_the_agent_types_it_lists(self, spawn: Spawn) -> None:
        result = spawn({"tdd": "  attach_roles: worker, tester\n"}, "Do the job")

        assert result.fallback_notes == ["HINT tdd"]

    def test_nothing_changes_for_other_tools_or_a_task_no_skill_fits(
        self, spawn: Spawn
    ) -> None:
        skills = {"tdd": "  attach_triggers: tests\n"}

        assert spawn(skills, "Write tests", "read") == HookResult()
        assert spawn(skills, "Tidy the docs") == HookResult()
