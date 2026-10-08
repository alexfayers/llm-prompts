"""Tests for Jinja rendering of prompt templates."""

from __future__ import annotations

import pytest
from jinja2 import TemplateSyntaxError

from llm_prompts.render_template import find_unreplaced_variables, substitute_variables

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

    def test_syntax_error_raises(self) -> None:
        with pytest.raises(TemplateSyntaxError):
            substitute_variables("{% if AGENT %}unclosed\n", {"AGENT": "pi"})
