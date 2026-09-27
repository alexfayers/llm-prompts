"""Tests for the eagle-vision skill's focus script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "shared"
    / "skills"
    / "eagle-vision"
    / "focus.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("focus", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod() -> ModuleType:
    """Load the focus script as a module."""
    return _load()


class TestRenderNodeFile:
    """Tests for rendering a node file's front matter."""

    def test_omits_empty_depends_and_scope_lines(self, mod: ModuleType) -> None:
        text = mod.render_node_file([], [], "body\n")
        assert text == "---\n---\nbody\n"

    def test_includes_only_non_empty_lines(self, mod: ModuleType) -> None:
        text = mod.render_node_file(["a"], [], "body\n")
        assert text == "---\ndepends: a\n---\nbody\n"

    def test_includes_both_lines_when_present(self, mod: ModuleType) -> None:
        text = mod.render_node_file(["a"], ["s/"], "body\n")
        assert text == "---\ndepends: a\nscope: s/\n---\nbody\n"

    def test_empty_front_matter_round_trips_through_parse(
        self, mod: ModuleType
    ) -> None:
        text = mod.render_node_file([], [], "body\n")
        front, body = mod.parse_node_file(text)
        assert front == {"depends": [], "scope": []}
        assert body == "body\n"


class TestLinksSummary:
    """Tests for the console depends/scope summary."""

    def test_empty_summary_is_blank(self, mod: ModuleType) -> None:
        assert mod.links_summary([], []) == ""

    def test_depends_only(self, mod: ModuleType) -> None:
        assert mod.links_summary(["a"], []) == " (depends: a)"

    def test_both_present(self, mod: ModuleType) -> None:
        assert mod.links_summary(["a"], ["s/"]) == " (depends: a; scope: s/)"


class TestAdd:
    """Tests for the add command's console output and file contents."""

    def test_add_with_no_links_prints_plain_path(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        capsys.readouterr()
        mod.cmd_add(base, "widget", [], [])
        out = capsys.readouterr().out
        path = mod.node_path(base, "widget", "todo")
        assert out == f"added {path}\n"
        assert path.read_text().startswith("---\n---\n")

    def test_add_with_links_prints_summary(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "base", [], [])
        capsys.readouterr()
        mod.cmd_add(base, "widget", ["base"], ["widget/"])
        out = capsys.readouterr().out
        path = mod.node_path(base, "widget", "todo")
        assert out == f"added {path} (depends: base; scope: widget/)\n"


class TestEditLinks:
    """Tests for the link/unlink command's output and preserved state."""

    def test_unlink_everything_prints_plain_id(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], ["widget/"])
        capsys.readouterr()
        mod.edit_links(base, "widget", [], ["widget/"], add=False)
        out = capsys.readouterr().out
        assert out == "widget\n"
        front, _ = mod.parse_node_file(
            mod.node_path(base, "widget", "todo").read_text()
        )
        assert front == {"depends": [], "scope": []}

    def test_link_preserves_failed_line(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "helper", [], [])
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_built(base, "widget")
        mod.cmd_fail(base, "widget", "why")
        capsys.readouterr()
        mod.edit_links(base, "widget", ["helper"], [], add=True)
        text = mod.node_path(base, "widget", "todo").read_text()
        assert "failed: why" in text
        assert "depends: helper" in text


class TestRemove:
    """Tests for the remove command."""

    def test_removes_node_file(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_remove(base, "widget")
        assert not mod.node_path(base, "widget", "todo").exists()
        assert "widget" not in mod.load_nodes(base)

    def test_refuses_with_dependents(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "base", [], [])
        mod.cmd_add(base, "widget", ["base"], [])
        with pytest.raises(mod.FocusError, match="depended on by widget"):
            mod.cmd_remove(base, "base")
        assert mod.node_path(base, "base", "todo").exists()

    def test_unknown_id_raises(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        with pytest.raises(mod.FocusError, match="unknown node 'nope'"):
            mod.cmd_remove(base, "nope")

    def test_removes_a_done_node(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_built(base, "widget")
        mod.cmd_pass(base, "widget")
        mod.cmd_remove(base, "widget")
        assert not mod.node_path(base, "widget", "done").exists()


class TestRename:
    """Tests for the rename command."""

    def test_renames_node_file(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_rename(base, "widget", "gadget")
        assert not mod.node_path(base, "widget", "todo").exists()
        new_path = mod.node_path(base, "gadget", "todo")
        assert new_path.exists()
        assert new_path.read_text().startswith("---\n---\n# gadget\n")

    def test_updates_dependents_preserving_order_and_failed_line(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_add(base, "other", [], [])
        mod.cmd_add(base, "gizmo", ["widget", "other"], [])
        mod.cmd_built(base, "gizmo")
        mod.cmd_fail(base, "gizmo", "why")
        mod.cmd_rename(base, "widget", "gadget")
        front, _ = mod.parse_node_file(mod.node_path(base, "gizmo", "todo").read_text())
        assert front["depends"] == ["gadget", "other"]
        assert "failed: why" in mod.node_path(base, "gizmo", "todo").read_text()

    def test_plan_graph_shows_new_id(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_rename(base, "widget", "gadget")
        plan = mod.plan_path(base).read_text()
        assert "gadget" in plan
        assert "widget" not in plan

    def test_target_exists_raises(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_add(base, "gadget", [], [])
        with pytest.raises(mod.FocusError, match="node 'gadget' already exists"):
            mod.cmd_rename(base, "widget", "gadget")

    def test_unknown_id_raises(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        with pytest.raises(mod.FocusError, match="unknown node 'nope'"):
            mod.cmd_rename(base, "nope", "gadget")

    def test_rename_to_same_name_raises(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        with pytest.raises(mod.FocusError, match="node 'widget' already exists"):
            mod.cmd_rename(base, "widget", "widget")


class TestGraph:
    """Tests for the plan's generated mermaid Graph section."""

    def test_reserved_word_hyphenated_id_gets_safe_id_and_label(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "end-to-end", [], [])
        graph = mod.parse_sections(mod.plan_path(base).read_text())["Graph"]
        assert 'end_to_end["end-to-end"]' in graph
        assert "end-to-end" not in graph.replace('end_to_end["end-to-end"]', "")

    def test_dependency_edge_uses_safe_ids_on_both_sides(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "end-to-end", [], [])
        mod.cmd_add(base, "widget", ["end-to-end"], [])
        graph = mod.parse_sections(mod.plan_path(base).read_text())["Graph"]
        assert 'end_to_end["end-to-end"] --> widget["widget"]' in graph

    def test_done_classdef_line_uses_safe_id(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "end-to-end", [], [])
        mod.cmd_built(base, "end-to-end")
        mod.cmd_pass(base, "end-to-end")
        graph = mod.parse_sections(mod.plan_path(base).read_text())["Graph"]
        assert "end_to_end:::done" in graph


class TestParseChecks:
    """Tests for parsing the plan's Checks section into shell commands."""

    def test_extracts_bullet_lines(self, mod: ModuleType) -> None:
        assert mod.parse_checks("- pytest\n- ruff check\n") == ["pytest", "ruff check"]

    def test_ignores_non_bullet_lines(self, mod: ModuleType) -> None:
        assert mod.parse_checks("notes\n- pytest\n") == ["pytest"]

    def test_strips_surrounding_backticks(self, mod: ModuleType) -> None:
        assert mod.parse_checks("- `pytest -q`\n") == ["pytest -q"]


class TestChecksSection:
    """Tests for the plan's free-text Checks section."""

    def test_checks_section_appears_in_new_plan(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        assert "## Checks" in mod.plan_path(base).read_text()

    def test_regenerate_plan_preserves_checks_text(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = "- pytest\n- ruff check"
        plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "widget", [], [])
        assert "- pytest" in mod.plan_path(base).read_text()


class TestNodeTestCommand:
    """Tests for reading a node's test command from front matter."""

    def test_returns_none_when_absent(self, mod: ModuleType) -> None:
        text = mod.render_node_file([], [], "body\n")
        assert mod.node_test_command(text) is None

    def test_returns_value_when_present(self, mod: ModuleType) -> None:
        text = "---\ntest: pytest -k widget\n---\nbody\n"
        assert mod.node_test_command(text) == "pytest -k widget"


class TestSetTest:
    """Tests for the set-test command."""

    def test_writes_front_matter_line_and_prints_summary(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        capsys.readouterr()
        mod.cmd_set_test(base, "widget", "pytest -k widget")
        out = capsys.readouterr().out
        assert out == "widget test: pytest -k widget\n"
        text = mod.node_path(base, "widget", "todo").read_text()
        assert "test: pytest -k widget" in text

    def test_rejects_multiline_command(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        with pytest.raises(mod.FocusError, match="test command must be one line"):
            mod.cmd_set_test(base, "widget", "a\nb")

    def test_unknown_id_raises(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        with pytest.raises(mod.FocusError, match="unknown node 'nope'"):
            mod.cmd_set_test(base, "nope", "pytest")


class TestCheck:
    """Tests for the check command."""

    def test_requires_testing_stage(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        with pytest.raises(mod.FocusError, match="'widget' is not in nodes/testing"):
            mod.cmd_check(base, "widget")

    def test_requires_test_command(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_built(base, "widget")
        with pytest.raises(mod.FocusError, match="'widget' has no test command"):
            mod.cmd_check(base, "widget")

    def test_passing_command_moves_node_to_done(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_built(base, "widget")
        mod.cmd_set_test(base, "widget", "true")
        capsys.readouterr()
        mod.cmd_check(base, "widget")
        out = capsys.readouterr().out
        assert out == "$ true\npass widget\n"
        assert mod.node_path(base, "widget", "done").exists()

    def test_failing_command_fails_node_and_exits(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_built(base, "widget")
        mod.cmd_set_test(base, "widget", "false")
        with pytest.raises(SystemExit) as exc_info:
            mod.cmd_check(base, "widget")
        assert exc_info.value.code == 1
        text = mod.node_path(base, "widget", "todo").read_text()
        assert "failed: `false` exited 1" in text

    def test_runs_plan_checks_after_node_command(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = "- true"
        plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_built(base, "widget")
        mod.cmd_set_test(base, "widget", "true")
        capsys.readouterr()
        mod.cmd_check(base, "widget")
        out = capsys.readouterr().out
        assert out == "$ true\n$ true\npass widget\n"


class TestReady:
    """Tests for the ready command."""

    def test_requires_test_command(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = "- true"
        plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "widget", [], [])
        with pytest.raises(mod.FocusError, match="'widget' has no test command"):
            mod.cmd_ready(base, "widget")

    def test_requires_plan_checks(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_set_test(base, "widget", "true")
        with pytest.raises(mod.FocusError, match="plan has no Checks"):
            mod.cmd_ready(base, "widget")

    def test_waiting_on_unfinished_dependency(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = "- true"
        plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "gadget", [], [])
        mod.cmd_add(base, "widget", ["gadget"], [])
        mod.cmd_set_test(base, "widget", "true")
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc_info:
            mod.cmd_ready(base, "widget")
        assert exc_info.value.code == 1
        assert capsys.readouterr().out == "waiting on: gadget\n"

    def test_ready_prints_ready(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = "- true"
        plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "widget", [], [])
        mod.cmd_set_test(base, "widget", "true")
        capsys.readouterr()
        mod.cmd_ready(base, "widget")
        assert capsys.readouterr().out == "ready\n"


class TestShow:
    """Tests for the show command's plan output."""

    def test_show_includes_checks_section(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = "- pytest"
        plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "widget", [], [])
        capsys.readouterr()
        mod.cmd_show(base, "widget")
        out = capsys.readouterr().out
        assert "- pytest" in out


class TestComment:
    """Tests for the comment command's PR comment output."""

    def test_starts_with_heading_and_intro(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        capsys.readouterr()
        mod.cmd_comment(base)
        out = capsys.readouterr().out
        assert out.startswith("## Eagle-vision plan\n\n" + mod.COMMENT_INTRO)

    def test_plan_details_excludes_nodes_section_and_title(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Goal"] = "do the thing"
        sections["Checks"] = "- pytest"
        plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "widget", [], [])
        capsys.readouterr()
        mod.cmd_comment(base)
        out = capsys.readouterr().out
        assert "## Goal" in out
        assert "do the thing" in out
        assert "- pytest" in out
        assert "## Nodes" not in out
        assert f"# {base.name}" not in out

    def test_accept_details_lists_nodes_in_wave_then_id_order(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "base", [], [])
        mod.cmd_add(base, "zeta", ["base"], [])
        base_path = mod.node_path(base, "base", "todo")
        base_path.write_text(
            base_path.read_text().replace("## Accept\n", "## Accept\n\n- base check\n")
        )
        zeta_path = mod.node_path(base, "zeta", "todo")
        zeta_path.write_text(
            zeta_path.read_text().replace("## Accept\n", "## Accept\n\n- zeta check\n")
        )
        capsys.readouterr()
        mod.cmd_comment(base)
        out = capsys.readouterr().out
        assert out.index("### base") < out.index("### zeta")
        assert "- base check" in out
        assert "- zeta check" in out

    def test_show_output_is_unchanged_by_the_refactor(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "base", [], [])
        mod.cmd_add(base, "widget", ["base"], [])
        capsys.readouterr()
        mod.cmd_show(base, "widget")
        out = capsys.readouterr().out
        assert out.startswith(f"# {base.name}\n\n## Goal")
        assert "## base" in out


class TestCli:
    """Tests for CLI wiring of the remove and rename commands."""

    def test_remove_via_cli(
        self,
        mod: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        monkeypatch.setattr(sys, "argv", ["focus", "remove", str(base), "widget"])
        mod.main()
        assert not mod.node_path(base, "widget", "todo").exists()

    def test_rename_via_cli(
        self,
        mod: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", [], [])
        monkeypatch.setattr(
            sys, "argv", ["focus", "rename", str(base), "widget", "gadget"]
        )
        mod.main()
        assert mod.node_path(base, "gadget", "todo").exists()

    def test_focus_error_exits_with_message_on_stderr(
        self,
        mod: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        monkeypatch.setattr(sys, "argv", ["focus", "remove", str(base), "nope"])
        with pytest.raises(SystemExit) as exc_info:
            mod.main()
        assert exc_info.value.code == 1
        assert "unknown node 'nope'" in capsys.readouterr().err
