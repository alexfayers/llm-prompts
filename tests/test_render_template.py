"""Tests for Jinja rendering of prompt templates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest
from jinja2 import TemplateSyntaxError

from llm_prompts.render_template import (
    _JINJA_ENV,
    _read_text,
    find_unreplaced_variables,
    load_vars,
    substitute_variables,
)

BRANCHED = (
    "before\n"
    '{% if AGENT == "pi" %}\n'
    "pi line\n"
    "{% else %}\n"
    "other line\n"
    "{% endif %}\n"
    "after\n"
)


class TestSubstituteVariables:
    @pytest.mark.parametrize(
        ("agent", "branch"), [("pi", "pi line"), ("claude-code", "other line")]
    )
    def test_block_tags_on_own_lines_leave_no_blank_lines(
        self, agent: str, branch: str
    ) -> None:
        assert (
            substitute_variables(BRANCHED, {"AGENT": agent})
            == f"before\n{branch}\nafter\n"
        )

    def test_unknown_variable_stays_literal_and_is_reported(self) -> None:
        output = substitute_variables(
            "Use {{KNOWN}} and {{MISSING}}.\n{% if MISSING %}\nset\n{% endif %}\n",
            {"KNOWN": "x"},
        )

        assert output == "Use x and {{MISSING}}.\n"
        assert find_unreplaced_variables(output) == ["MISSING"]

    @pytest.mark.parametrize(("path", "expected"), [("/bin/tool", "yes\n"), (None, "")])
    def test_has_command_branches_on_path_lookup(
        self, monkeypatch: pytest.MonkeyPatch, path: str | None, expected: str
    ) -> None:
        monkeypatch.setattr("llm_prompts.render_template.shutil.which", lambda _: path)

        assert (
            substitute_variables('{% if has_command("tool") %}\nyes\n{% endif %}\n', {})
            == expected
        )

    def test_syntax_error_raises(self) -> None:
        with pytest.raises(TemplateSyntaxError):
            substitute_variables("{% if AGENT %}unclosed\n", {"AGENT": "pi"})


class TestReadText:
    def test_unchanged_file_is_read_once_and_changed_file_is_reread(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "file.txt"
        path.write_text("one", encoding="utf-8")
        original = Path.read_text

        with patch.object(
            Path, "read_text", autospec=True, side_effect=original
        ) as read_text:
            assert (_read_text(path), _read_text(path)) == ("one", "one")
            path.write_text("three", encoding="utf-8")
            assert _read_text(path) == "three"

        assert read_text.call_count == 2


class TestSubstituteVariablesCache:
    def test_same_content_is_compiled_once(self) -> None:
        with patch.object(
            _JINJA_ENV, "from_string", wraps=_JINJA_ENV.from_string
        ) as from_string:
            substitute_variables("cache probe {{A}}", {"A": "1"})
            substitute_variables("cache probe {{A}}", {"A": "2"})

        assert from_string.call_count == 1


class TestLoadVars:
    def test_target_values_override_shared(self, tmp_path: Path) -> None:
        (tmp_path / "shared").mkdir()
        (tmp_path / "shared" / "vars.json").write_text(
            json.dumps({"A": "shared", "B": "shared"}), encoding="utf-8"
        )
        (tmp_path / "pi").mkdir()
        target = tmp_path / "pi" / "vars.json"
        target.write_text(json.dumps({"B": "pi"}), encoding="utf-8")

        assert load_vars(target) == {"A": "shared", "B": "pi"}

    def test_missing_shared_file_is_fine(self, tmp_path: Path) -> None:
        (tmp_path / "pi").mkdir()
        target = tmp_path / "pi" / "vars.json"
        target.write_text(json.dumps({"B": "pi"}), encoding="utf-8")

        assert load_vars(target) == {"B": "pi"}


class TestSharedSourcesResolveToolVariables:
    PROMPTS = Path(__file__).parent.parent / "src/llm_prompts/prompts"
    PLACEHOLDER = re.compile(r"\{\{\s*(TOOL_[A-Z_]+)\s*\}\}")

    TARGET_VARS: ClassVar[list[Path]] = sorted(
        path for path in PROMPTS.glob("*/vars.json") if path.parent.name != "shared"
    )

    @pytest.mark.parametrize("target_vars", TARGET_VARS, ids=lambda p: p.parent.name)
    def test_every_tool_placeholder_in_shared_sources_is_defined(
        self, target_vars: Path
    ) -> None:
        used = {
            name
            for source in (self.PROMPTS / "shared").rglob("*.md")
            for name in self.PLACEHOLDER.findall(source.read_text(encoding="utf-8"))
        }

        assert used <= load_vars(target_vars).keys()


class TestHerdsmanOverrides:
    TEMPLATE = (
        "{{TOOL_AGENT}}|{{TOOL_STEER}}|{{TOOL_AGENT_RESULT}}|[{{TOOL_WORKFLOW}}]\n"
    )
    VARIABLES: ClassVar[dict[str, str]] = {
        "TOOL_AGENT": "Agent",
        "TOOL_STEER": "steer_subagent",
        "TOOL_AGENT_RESULT": "get_subagent_result",
        "TOOL_WORKFLOW": "SubagentWorkflow",
    }

    @pytest.mark.parametrize(
        ("agent", "expected"),
        [
            ("pi", "delegate_agent|steer_agent|inspect_agent|[]\n"),
            (
                "claude-code",
                "Agent|steer_subagent|get_subagent_result|[SubagentWorkflow]\n",
            ),
        ],
    )
    def test_overrides_apply_only_to_pi(self, agent: str, expected: str) -> None:
        assert (
            substitute_variables(self.TEMPLATE, {**self.VARIABLES, "AGENT": agent})
            == expected
        )


class TestSourcesUseToolVariables:
    DELEGATION = Path(__file__).parent.parent / (
        "src/llm_prompts/prompts/shared/rules/delegation.md"
    )

    @pytest.mark.parametrize(
        ("agent", "present", "absent"),
        [
            ("pi", "`continue_agent`", "`Agent`"),
            ("claude-code", "`Agent`", "continue_agent"),
        ],
    )
    def test_delegation_rule_tool_names(
        self, agent: str, present: str, absent: str
    ) -> None:
        variables = {
            **load_vars(self.DELEGATION.parents[2] / agent / "vars.json"),
            "AGENT": agent,
        }

        output = substitute_variables(
            self.DELEGATION.read_text(encoding="utf-8"), variables
        )

        assert present in output
        assert absent not in output


class TestDelegationModelOptionsArePiOnly:
    SHARED = Path(__file__).parent.parent / "src/llm_prompts/prompts/shared"
    SOURCES = ("rules/delegation.md", "agents/reasoner.md")
    PI_OPTIONS = ("`opus`", "`sonnet`", "`haiku`")
    GPT_NAMES = re.compile(r"`(sol|terra|luna)`")

    def _render(self, source: str, agent: str) -> str:
        variables = {
            **load_vars(self.SHARED.parent / agent / "vars.json"),
            "AGENT": agent,
        }
        return substitute_variables(
            (self.SHARED / source).read_text(encoding="utf-8"), variables
        )

    @pytest.mark.parametrize("agent", ["claude-code", "cline", "copilot", "kiro"])
    @pytest.mark.parametrize("source", SOURCES)
    def test_non_pi_targets_name_no_gpt_models(self, agent: str, source: str) -> None:
        output = self._render(source, agent)

        assert not self.GPT_NAMES.search(output)

    def test_claude_code_delegation_keeps_claude_tiers(self) -> None:
        output = self._render("rules/delegation.md", "claude-code")

        assert all(tier in output for tier in ("**Opus**", "**Sonnet**", "**Haiku**"))

    def test_pi_delegation_names_a_model_per_job(self) -> None:
        output = self._render("rules/delegation.md", "pi")

        assert all(option in output for option in self.PI_OPTIONS)

    @pytest.mark.parametrize("source", SOURCES)
    def test_pi_names_no_gpt_models(self, source: str) -> None:
        assert not self.GPT_NAMES.search(self._render(source, "pi"))


class TestReloadRuleIsPiOnly:
    SHARED = Path(__file__).parent.parent / "src/llm_prompts/prompts/shared"
    SOURCE = "rules/000-rule-sources.md"
    RELOAD = "`/reload`"

    def _render(self, agent: str) -> str:
        variables = {
            **load_vars(self.SHARED.parent / agent / "vars.json"),
            "AGENT": agent,
        }
        return substitute_variables(
            (self.SHARED / self.SOURCE).read_text(encoding="utf-8"), variables
        )

    def test_pi_tells_user_to_reload(self) -> None:
        assert self.RELOAD in self._render("pi")

    @pytest.mark.parametrize("agent", ["claude-code", "cline", "copilot", "kiro"])
    def test_other_targets_do_not_mention_reload(self, agent: str) -> None:
        assert self.RELOAD not in self._render(agent)


class TestPlanningRuleLinesAreClaudeCodeOnly:
    SHARED = Path(__file__).parent.parent / "src/llm_prompts/prompts/shared"
    CLAUDE_CODE_LINES = (
        "MUST NOT skip the agent phase and plan in your head.",
        "MUST NOT assume a broad mandate from a narrow request.",
    )

    def _render(self, source: str, agent: str) -> str:
        variables = {
            **load_vars(self.SHARED.parent / agent / "vars.json"),
            "AGENT": agent,
        }
        return substitute_variables(
            (self.SHARED / source).read_text(encoding="utf-8"), variables
        )

    @pytest.mark.parametrize("line", CLAUDE_CODE_LINES)
    def test_claude_code_planning_keeps_line(self, line: str) -> None:
        assert line in self._render("rules/planning.md", "claude-code")

    @pytest.mark.parametrize("line", CLAUDE_CODE_LINES)
    def test_pi_planning_drops_line(self, line: str) -> None:
        assert line not in self._render("rules/planning.md", "pi")

    def test_claude_code_agent_teams_does_not_name_tower_do_patch(self) -> None:
        assert "tower_do_patch" not in self._render(
            "rules/agent-teams.md", "claude-code"
        )

    def test_pi_agent_teams_names_tower_do_patch(self) -> None:
        assert "tower_do_patch" in self._render("rules/agent-teams.md", "pi")


class TestStartUpStepsAreHookDriven:
    SHARED = Path(__file__).parent.parent / "src/llm_prompts/prompts/shared"

    @pytest.mark.parametrize(
        ("agent", "kept"), [("claude-code", False), ("pi", False), ("kiro", True)]
    )
    def test_only_legacy_agents_keep_the_start_up_instructions(
        self, agent: str, kept: bool
    ) -> None:
        def render(source: str) -> str:
            text = (self.SHARED / source).read_text(encoding="utf-8")
            return substitute_variables(text, {"AGENT": agent})

        assert ("first tool call" in render("rules/002-skill-usage.md")) is kept
        assert (
            "`read_graph(project=" in render("skills/session-start/SKILL.md")
        ) is kept
