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
