"""Tests for the eagle-vision skill's focus script."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from conftest import FakeSubprocess

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


@pytest.fixture(autouse=True)
def fake_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer the shell check commands (`true`, `false`, `test 1 = 1`, `exit N`) without spawning a shell."""
    real_run = subprocess.run
    statuses = {"true": 0, "false": 1, "test 1 = 1": 0}

    def run(
        command: str | list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if not isinstance(command, str):
            return real_run(command, **kwargs)
        name, _, argument = command.partition(" ")
        status = int(argument) if name == "exit" else statuses[command]
        return subprocess.CompletedProcess(command, status, "", "")

    monkeypatch.setattr(subprocess, "run", run)


@pytest.fixture
def mod() -> ModuleType:
    """Load the focus script as a module."""
    return _load()


class TestRenderNodeFile:
    """Tests for rendering a node file's front matter."""

    def test_omits_empty_depends_and_scope_lines(self, mod: ModuleType) -> None:
        text = mod.render_node_file({}, "body\n")
        assert text == "---\n---\nbody\n"

    def test_includes_only_non_empty_lines(self, mod: ModuleType) -> None:
        text = mod.render_node_file({"depends": ["a"]}, "body\n")
        assert text == "---\ndepends: a\n---\nbody\n"

    def test_includes_both_lines_when_present(self, mod: ModuleType) -> None:
        text = mod.render_node_file({"depends": ["a"], "scope": ["s/"]}, "body\n")
        assert text == "---\ndepends: a\nscope: s/\n---\nbody\n"

    def test_empty_front_matter_round_trips_through_parse(
        self, mod: ModuleType
    ) -> None:
        text = mod.render_node_file({}, "body\n")
        front, body = mod.parse_node_file(text)
        assert front == {key: [] for key in mod.LINK_KEYS}
        assert body == "body\n"

    def test_includes_inputs_outputs_deletes_in_key_order(
        self, mod: ModuleType
    ) -> None:
        links = {"deletes": ["d"], "outputs": ["o"], "inputs": ["i"], "depends": ["a"]}
        text = mod.render_node_file(links, "body\n")
        assert text == "---\ndepends: a\ninputs: i\noutputs: o\ndeletes: d\n---\nbody\n"
        front, _ = mod.parse_node_file(text)
        assert front == {
            **{key: [] for key in mod.LINK_KEYS},
            "depends": ["a"],
            "inputs": ["i"],
            "outputs": ["o"],
            "deletes": ["d"],
        }


class TestLinksSummary:
    """Tests for the console depends/scope summary."""

    def test_empty_summary_is_blank(self, mod: ModuleType) -> None:
        assert mod.links_summary({}) == ""

    def test_depends_only(self, mod: ModuleType) -> None:
        assert mod.links_summary({"depends": ["a"]}) == " (depends: a)"

    def test_both_present(self, mod: ModuleType) -> None:
        assert (
            mod.links_summary({"depends": ["a"], "scope": ["s/"]})
            == " (depends: a; scope: s/)"
        )


class TestAdd:
    """Tests for the add command's console output and file contents."""

    def test_add_with_no_links_prints_plain_path(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        capsys.readouterr()
        mod.cmd_add(base, "widget", {})
        out = capsys.readouterr().out
        path = mod.node_path(base, "widget", "todo")
        assert out == f"added {path}\n"
        assert path.read_text().startswith("---\n---\n")

    def test_add_with_links_prints_summary(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "base", {})
        capsys.readouterr()
        mod.cmd_add(base, "widget", {"depends": ["base"], "scope": ["widget/"]})
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
        mod.cmd_add(base, "widget", {"scope": ["widget/"]})
        capsys.readouterr()
        mod.edit_links(base, "widget", {"scope": ["widget/"]}, add=False)
        out = capsys.readouterr().out
        assert out == "widget\n"
        front, _ = mod.parse_node_file(
            mod.node_path(base, "widget", "todo").read_text()
        )
        assert front == {key: [] for key in mod.LINK_KEYS}

    def test_link_preserves_failed_line(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "helper", {})
        mod.cmd_add(base, "widget", {})
        mod.cmd_built(base, "widget")
        mod.cmd_fail(base, "widget", "why")
        capsys.readouterr()
        mod.edit_links(base, "widget", {"depends": ["helper"]}, add=True)
        text = mod.node_path(base, "widget", "todo").read_text()
        assert "failed: why" in text
        assert "depends: helper" in text


class TestRemove:
    """Tests for the remove command."""

    def test_removes_node_file(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        mod.cmd_remove(base, "widget")
        assert not mod.node_path(base, "widget", "todo").exists()
        assert "widget" not in mod.load_nodes(base)

    def test_refuses_with_dependents(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "base", {})
        mod.cmd_add(base, "widget", {"depends": ["base"]})
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
        mod.cmd_add(base, "widget", {})
        mod.cmd_built(base, "widget")
        mod.cmd_pass(base, "widget")
        mod.cmd_remove(base, "widget")
        assert not mod.node_path(base, "widget", "done").exists()


class TestRename:
    """Tests for the rename command."""

    def test_renames_node_file(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
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
        mod.cmd_add(base, "widget", {})
        mod.cmd_add(base, "other", {})
        mod.cmd_add(base, "gizmo", {"depends": ["widget", "other"]})
        mod.cmd_built(base, "gizmo")
        mod.cmd_fail(base, "gizmo", "why")
        mod.cmd_rename(base, "widget", "gadget")
        front, _ = mod.parse_node_file(mod.node_path(base, "gizmo", "todo").read_text())
        assert front["depends"] == ["gadget", "other"]
        assert "failed: why" in mod.node_path(base, "gizmo", "todo").read_text()

    def test_plan_graph_shows_new_id(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        mod.cmd_rename(base, "widget", "gadget")
        plan = mod.plan_path(base).read_text()
        assert "gadget" in plan
        assert "widget" not in plan

    def test_target_exists_raises(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        mod.cmd_add(base, "gadget", {})
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
        mod.cmd_add(base, "widget", {})
        with pytest.raises(mod.FocusError, match="node 'widget' already exists"):
            mod.cmd_rename(base, "widget", "widget")


class TestGraph:
    """Tests for the plan's generated mermaid Graph section."""

    def test_reserved_word_hyphenated_id_gets_safe_id_and_label(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "end-to-end", {})
        graph = mod.parse_sections(mod.plan_path(base).read_text())["Graph"]
        assert 'end_to_end["end-to-end"]' in graph
        assert "end-to-end" not in graph.replace('end_to_end["end-to-end"]', "")

    def test_dependency_edge_uses_safe_ids_on_both_sides(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "end-to-end", {})
        mod.cmd_add(base, "widget", {"depends": ["end-to-end"]})
        graph = mod.parse_sections(mod.plan_path(base).read_text())["Graph"]
        assert 'end_to_end["end-to-end"] --> widget["widget"]' in graph

    def test_done_classdef_line_uses_safe_id(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "end-to-end", {})
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
        mod.cmd_add(base, "widget", {})
        assert "- pytest" in mod.plan_path(base).read_text()


class TestNodeTestCommand:
    """Tests for reading a node's test command from front matter."""

    def test_returns_none_when_absent(self, mod: ModuleType) -> None:
        text = mod.render_node_file({}, "body\n")
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
        mod.cmd_add(base, "widget", {})
        capsys.readouterr()
        mod.cmd_set_test(base, "widget", "pytest -k widget")
        out = capsys.readouterr().out
        assert out == "widget test: pytest -k widget\n"
        text = mod.node_path(base, "widget", "todo").read_text()
        assert "test: pytest -k widget" in text

    def test_rejects_multiline_command(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        with pytest.raises(mod.FocusError, match="test command must be one line"):
            mod.cmd_set_test(base, "widget", "a\nb")

    def test_unknown_id_raises(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        with pytest.raises(mod.FocusError, match="unknown node 'nope'"):
            mod.cmd_set_test(base, "nope", "pytest")


class TestOutsideScope:
    """Tests for filtering changed paths by a node's scope."""

    def test_path_under_dir_scope_is_inside(self, mod: ModuleType) -> None:
        assert mod.outside_scope(["src/a.py"], ["src/"]) == []

    def test_path_whose_section_is_the_scope_is_inside(self, mod: ModuleType) -> None:
        assert mod.outside_scope(["doc.md"], ["doc.md/Setup"]) == []

    def test_unrelated_paths_are_outside_and_sorted(self, mod: ModuleType) -> None:
        assert mod.outside_scope(["z.py", "src/a.py", "b.py"], ["src/"]) == [
            "b.py",
            "z.py",
        ]


class TestStart:
    """Tests for the start command and the building stage."""

    def test_moves_todo_to_building(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        capsys.readouterr()
        mod.cmd_start(base, "widget")
        assert capsys.readouterr().out == "start widget\n"
        assert not mod.node_path(base, "widget", "todo").exists()
        assert mod.node_path(base, "widget", "building").exists()

    def test_start_requires_todo(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        mod.cmd_start(base, "widget")
        with pytest.raises(mod.FocusError, match=r"'widget' is not in nodes/$"):
            mod.cmd_start(base, "widget")

    def test_built_accepts_building_only_once(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        mod.cmd_start(base, "widget")
        mod.cmd_built(base, "widget")
        assert mod.node_path(base, "widget", "testing").exists()
        with pytest.raises(mod.FocusError, match="is not in nodes/ or nodes/building"):
            mod.cmd_built(base, "widget")

    def test_fail_rejects_building(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        mod.cmd_start(base, "widget")
        with pytest.raises(mod.FocusError, match="is not in nodes/testing"):
            mod.cmd_fail(base, "widget", "broken")

    def test_waves_show_building(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        mod.cmd_start(base, "widget")
        nodes = mod.load_nodes(base)
        assert "- [ ] widget (building)" in mod.render_waves(nodes, nodes)

    def test_plan_graph_styles_building(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        mod.cmd_start(base, "widget")
        plan = mod.plan_path(base).read_text()
        assert "classDef building" in plan
        assert "widget:::building" in plan

    def test_init_creates_building_dir(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        assert (base / "nodes" / "building").is_dir()

    def test_start_recreates_missing_building_dir(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        (base / "nodes" / "building").rmdir()
        mod.cmd_start(base, "widget")
        assert mod.node_path(base, "widget", "building").exists()


class TestCheck:
    """Tests for the check command."""

    def test_requires_testing_stage(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        with pytest.raises(mod.FocusError, match="'widget' is not in nodes/testing"):
            mod.cmd_check(base, "widget")

    def test_requires_test_command(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        mod.cmd_built(base, "widget")
        with pytest.raises(mod.FocusError, match="'widget' has no test command"):
            mod.cmd_check(base, "widget")

    def test_passing_command_moves_node_to_done(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
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
        mod.cmd_add(base, "widget", {})
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
        mod.cmd_add(base, "widget", {})
        mod.cmd_built(base, "widget")
        mod.cmd_set_test(base, "widget", "true")
        capsys.readouterr()
        mod.cmd_check(base, "widget")
        out = capsys.readouterr().out
        assert out == "$ true\n$ true\npass widget\n"

    def test_node_only_skips_plan_checks(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = "- false"
        plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "widget", {})
        mod.cmd_built(base, "widget")
        mod.cmd_set_test(base, "widget", "true")
        capsys.readouterr()
        mod.cmd_check(base, "widget", node_only=True)
        assert capsys.readouterr().out == "$ true\npass widget\n"
        assert mod.node_path(base, "widget", "done").exists()


class TestCheckWave:
    """Tests for the check-wave command."""

    def _plan_with_checks(self, mod: ModuleType, tmp_path: Path, checks: str) -> Path:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = checks
        plan.write_text(mod.render_plan(base.name, sections))
        return base

    def test_runs_each_check(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan_with_checks(mod, tmp_path, "- true\n- test 1 = 1")
        capsys.readouterr()
        mod.cmd_check_wave(base)
        assert capsys.readouterr().out == "$ true\n$ test 1 = 1\n"

    def test_runs_every_check_and_names_each_failure(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan_with_checks(
            mod, tmp_path, "- true\n- false\n- true\n- exit 3"
        )
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc_info:
            mod.cmd_check_wave(base)
        assert exc_info.value.code == 1
        assert capsys.readouterr().out == (
            "$ true\n$ false\n`false` exited 1\n$ true\n$ exit 3\n`exit 3` exited 3\n"
        )


class TestCollect:
    """Tests for the collect command."""

    def _plan(self, mod: ModuleType, tmp_path: Path, collect: str | None) -> Path:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        if collect is not None:
            plan = mod.plan_path(base)
            sections = mod.parse_sections(plan.read_text())
            sections["Collect"] = collect
            plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "widget", {})
        return base

    def test_collect_section_appears_in_new_plan_and_survives_regenerate(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = self._plan(mod, tmp_path, "- pytest --collect-only {test}")
        text = mod.plan_path(base).read_text()
        assert (
            text.index("## Checks") < text.index("## Collect") < text.index("## Later")
        )
        assert "- pytest --collect-only {test}" in text

    def test_passes_when_template_exits_zero_and_keeps_stage(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan(mod, tmp_path, "- {test}")
        mod.cmd_set_test(base, "widget", "true")
        capsys.readouterr()
        mod.cmd_collect(base, "widget")
        assert capsys.readouterr().out == "$ true\n"
        assert mod.node_path(base, "widget", "todo").exists()

    def test_failing_template_names_node_and_exit_code_and_exits(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan(mod, tmp_path, "- {test}")
        mod.cmd_set_test(base, "widget", "exit 5")
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc_info:
            mod.cmd_collect(base, "widget")
        assert exc_info.value.code == 1
        assert capsys.readouterr().out == (
            "$ exit 5\n`widget` selects no tests: `exit 5` exited 5\n"
        )
        assert mod.node_path(base, "widget", "todo").exists()

    @pytest.mark.parametrize(
        ("collect", "test_command", "message"),
        [
            ("", "true", "plan has no Collect command"),
            ("- pytest --collect-only", "true", r"Collect command needs \{test\}"),
            ("- {test}", None, "'widget' has no test command"),
        ],
    )
    def test_errors(
        self,
        mod: ModuleType,
        tmp_path: Path,
        collect: str,
        test_command: str | None,
        message: str,
    ) -> None:
        base = self._plan(mod, tmp_path, collect)
        if test_command:
            mod.cmd_set_test(base, "widget", test_command)
        with pytest.raises(mod.FocusError, match=message):
            mod.cmd_collect(base, "widget")

    def test_cli_resolves_child_plan_node_from_parent_dir(
        self,
        mod: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        parent = tmp_path / "plans"
        parent.mkdir()
        mod.plan_path(parent).write_text("# plans\n")
        child = self._plan(mod, parent, "- {test}")
        mod.cmd_set_test(child, "widget", "true")
        capsys.readouterr()
        monkeypatch.setattr(
            sys, "argv", ["focus", "collect", str(parent), "plan/widget"]
        )
        mod.main()
        assert capsys.readouterr().out == "$ true\n"


class TestScopeFile:
    """Tests for reducing a scope entry to its file."""

    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            ("src/x.py/Sym/attr", "src/x.py"),
            ("docs/", "docs"),
            (".github/workflows/ci.yml/job", ".github/workflows/ci.yml"),
        ],
    )
    def test_scope_file(self, mod: ModuleType, entry: str, expected: str) -> None:
        assert mod.scope_file(entry) == expected


class TestSameFileWaves:
    """Tests for spreading nodes that share a file across waves."""

    def _waves(self, mod: ModuleType, base: Path) -> dict[str, int]:
        nodes = mod.load_nodes(base)
        waves: dict[str, int] = mod.compute_waves(nodes, mod.with_siblings(base, nodes))
        return waves

    def _plan(self, mod: ModuleType, tmp_path: Path) -> Path:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        return base

    def test_same_file_node_with_slack_moves_to_a_later_wave(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = self._plan(mod, tmp_path)
        mod.cmd_add(base, "a", {"scope": ["f.py/A"]})
        mod.cmd_add(base, "b", {"scope": ["f.py/B"]})
        mod.cmd_add(base, "c", {"depends": ["a"]})
        assert self._waves(mod, base) == {"a": 1, "b": 2, "c": 2}

    def test_same_file_nodes_without_slack_stay_together(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = self._plan(mod, tmp_path)
        mod.cmd_add(base, "a", {"scope": ["f.py/A"]})
        mod.cmd_add(base, "b", {"scope": ["f.py/B"]})
        mod.cmd_add(base, "c", {"depends": ["a"]})
        mod.cmd_add(base, "d", {"depends": ["b"]})
        assert self._waves(mod, base) == {"a": 1, "b": 1, "c": 2, "d": 2}

    def test_same_path_in_different_plan_dirs_is_not_separated(
        self,
        mod: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        parent = tmp_path / "plans"
        parent.mkdir()
        mod.plan_path(parent).write_text("# plans\n")
        for name in ("core", "app"):
            mod.cmd_init(parent / name)
            mod.cmd_add(parent / name, "widget", {"scope": ["f.py/A"]})
        mod.cmd_add(parent / "app", "step", {})
        mod.cmd_add(parent / "app", "gadget", {"depends": ["step"]})
        capsys.readouterr()
        monkeypatch.setattr(sys, "argv", ["focus", "waves", str(parent)])
        mod.main()
        assert capsys.readouterr().out == (
            "### Wave 1\n- [ ] app/step (ready)\n- [ ] app/widget (ready)\n"
            "- [ ] core/widget (ready)\n\n"
            "### Wave 2\n- [ ] app/gadget\n"
        )

    def test_marking_a_node_done_keeps_wave_numbers(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = self._plan(mod, tmp_path)
        mod.cmd_add(base, "a", {"scope": ["f.py/A"]})
        mod.cmd_add(base, "b", {"scope": ["f.py/B"]})
        mod.cmd_add(base, "c", {"depends": ["a"]})
        before = self._waves(mod, base)
        for step in (mod.cmd_start, mod.cmd_built, mod.cmd_pass):
            step(base, "a")
        assert self._waves(mod, base) == before


class TestJoinWarning:
    """Tests for the join command's advisory warning on mentions without a depends path."""

    WARNING = "warning: user mentions `Thing`, output of maker, with no depends path\n"

    def _plan(self, mod: ModuleType, tmp_path: Path) -> Path:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "maker", {"outputs": ["Thing"]})
        mod.cmd_add(base, "user", {})
        self._mention(mod, base, "user", "Thing")
        return base

    def _mention(self, mod: ModuleType, base: Path, node_id: str, span: str) -> None:
        path = mod.find_node_path(base, node_id)
        path.write_text(path.read_text() + f"\nUses `{span}`.\n")

    def test_warns_on_output_mention_with_no_depends_path(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan(mod, tmp_path)
        capsys.readouterr()
        mod.cmd_join(base)
        captured = capsys.readouterr()
        assert captured.out == "nothing to join\n"
        assert captured.err == self.WARNING

    def test_no_warning_when_a_depends_path_exists_or_output_is_own(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan(mod, tmp_path)
        mod.cmd_add(base, "mid", {"depends": ["maker"]})
        mod.edit_links(base, "user", {"depends": ["mid"]}, add=True)
        self._mention(mod, base, "maker", "Thing")
        capsys.readouterr()
        mod.cmd_join(base)
        assert capsys.readouterr().err == ""
        mod.edit_links(base, "user", {"depends": ["mid"]}, add=False)
        mod.edit_links(base, "maker", {"depends": ["user"]}, add=True)
        mod.cmd_join(base)
        assert capsys.readouterr().err == ""

    def test_no_warning_when_an_interface_node_mediates(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan(mod, tmp_path)
        mod.edit_links(base, "user", {"inputs": ["Thing"]}, add=True)
        capsys.readouterr()
        mod.cmd_join(base)
        assert capsys.readouterr().err == ""

    def test_names_sibling_producer_by_its_dir_and_ignores_call_signature(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parent = tmp_path / "plans"
        parent.mkdir()
        for name in ("core", "app"):
            mod.cmd_init(parent / name)
        mod.cmd_add(parent / "core", "maker", {"outputs": ["Thing"]})
        mod.cmd_add(parent / "app", "user", {})
        self._mention(mod, parent / "app", "user", "Thing(x)")
        capsys.readouterr()
        mod.cmd_join(parent / "app")
        assert capsys.readouterr().err == (
            "warning: user mentions `Thing`, output of core/maker, with no depends path\n"
        )

    def test_no_warning_when_a_sibling_interface_node_mediates(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parent = tmp_path / "plans"
        parent.mkdir()
        for name in ("core", "app"):
            mod.cmd_init(parent / name)
        mod.cmd_add(parent / "core", "maker", {"outputs": ["Thing"]})
        mod.cmd_add(parent / "core", "interface-thing", {"outputs": ["Thing"]})
        mod.cmd_add(parent / "app", "user", {"depends": ["core/interface-thing"]})
        self._mention(mod, parent / "app", "user", "Thing")
        capsys.readouterr()
        mod.cmd_join(parent / "app")
        assert capsys.readouterr().err == ""


class TestCheckBase:
    """Tests for the check command's --base scope gate."""

    def _built_widget(self, mod: ModuleType, repo: Path) -> Path:
        base = repo / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {"scope": ["src/"]})
        mod.cmd_built(base, "widget")
        mod.cmd_set_test(base, "widget", "true")
        return base

    def _fake_git(
        self,
        fake: FakeSubprocess,
        repo: Path,
        changed: str = "",
        merge_base_rc: int = 0,
    ) -> None:
        fake.on("rev-parse", "--show-toplevel", stdout=f"{repo}\n")
        fake.on("merge-base", stdout="abc123\n", returncode=merge_base_rc, stderr="bad")
        fake.on("diff", "--name-only", stdout=changed)

    def test_out_of_scope_change_fails_node(
        self, mod: ModuleType, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        base = self._built_widget(mod, tmp_path)
        self._fake_git(fake_subprocess, tmp_path, "stray.py\n")
        with pytest.raises(SystemExit) as exc_info:
            mod.cmd_check(base, "widget", "HEAD")
        assert exc_info.value.code == 1
        text = mod.node_path(base, "widget", "todo").read_text()
        assert "failed: outside scope: stray.py" in text

    def test_in_scope_change_passes(
        self, mod: ModuleType, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        base = self._built_widget(mod, tmp_path)
        self._fake_git(fake_subprocess, tmp_path, "src/a.py\n")
        mod.cmd_check(base, "widget", "HEAD")
        assert mod.node_path(base, "widget", "done").exists()

    def test_plan_dir_changes_are_ignored(
        self, mod: ModuleType, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        base = self._built_widget(mod, tmp_path)
        self._fake_git(fake_subprocess, tmp_path, "plan/PLAN.md\n")
        mod.cmd_check(base, "widget", "HEAD")
        assert mod.node_path(base, "widget", "done").exists()

    def test_bad_base_raises(
        self, mod: ModuleType, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        base = self._built_widget(mod, tmp_path)
        self._fake_git(fake_subprocess, tmp_path, merge_base_rc=128)
        with pytest.raises(mod.FocusError):
            mod.cmd_check(base, "widget", "no-such-ref")


class TestReady:
    """Tests for the ready command."""

    def test_requires_test_command(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = "- true"
        plan.write_text(mod.render_plan(base.name, sections))
        mod.cmd_add(base, "widget", {})
        with pytest.raises(mod.FocusError, match="'widget' has no test command"):
            mod.cmd_ready(base, "widget")

    def test_requires_plan_checks(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
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
        mod.cmd_add(base, "gadget", {})
        mod.cmd_add(base, "widget", {"depends": ["gadget"]})
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
        mod.cmd_add(base, "widget", {})
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
        mod.cmd_add(base, "widget", {})
        capsys.readouterr()
        mod.cmd_show(base, "widget")
        out = capsys.readouterr().out
        assert "- pytest" in out


class TestBriefs:
    """Tests for the briefs command's checker payload."""

    def test_plan_omits_nodes_and_graph(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "base", {})
        mod.cmd_add(base, "widget", {"depends": ["base"]})
        capsys.readouterr()
        mod.cmd_briefs(base)
        plan = json.loads(capsys.readouterr().out)["plan"]
        assert "## Goal" in plan
        assert "## Nodes" not in plan
        assert "## Graph" not in plan

    def test_node_brief_has_node_file_and_dependency_out(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "base", {})
        mod.cmd_add(base, "widget", {"depends": ["base"]})
        base_path = mod.node_path(base, "base", "todo")
        base_path.write_text(
            base_path.read_text().replace("## Out\n", "## Out\n\n- make_base()\n")
        )
        capsys.readouterr()
        mod.cmd_briefs(base)
        nodes = json.loads(capsys.readouterr().out)["nodes"]
        widget_file = mod.node_path(base, "widget", "todo").read_text()
        assert nodes["widget"].startswith(widget_file)
        assert "## base\n\n- make_base()" in nodes["widget"]
        assert set(nodes) == {"base", "widget"}

    def test_out_writes_plan_then_node_brief_per_node(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        out = tmp_path / "briefs"
        mod.cmd_init(base)
        mod.cmd_add(base, "base", {})
        mod.cmd_add(base, "widget", {"depends": ["base"]})
        capsys.readouterr()
        mod.cmd_briefs(base)
        payload = json.loads(capsys.readouterr().out)
        mod.cmd_briefs(base, out)
        assert capsys.readouterr().out.splitlines() == [
            str(out / "base.md"),
            str(out / "widget.md"),
        ]
        for node_id, brief in payload["nodes"].items():
            assert (out / f"{node_id}.md").read_text() == payload["plan"] + brief


class TestComment:
    """Tests for the comment command's PR comment output."""

    def test_starts_with_heading_and_intro(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
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
        mod.cmd_add(base, "widget", {})
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
        mod.cmd_add(base, "base", {})
        mod.cmd_add(base, "zeta", {"depends": ["base"]})
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
        mod.cmd_add(base, "base", {})
        mod.cmd_add(base, "widget", {"depends": ["base"]})
        capsys.readouterr()
        mod.cmd_show(base, "widget")
        out = capsys.readouterr().out
        assert out.startswith(f"# {base.name}\n\n## Goal")
        assert "## base" in out


class TestJoin:
    """Tests for the join command."""

    def _plan(self, mod: ModuleType, tmp_path: Path) -> Path:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "maker", {"outputs": ["Thing"]})
        mod.cmd_add(base, "user", {"inputs": ["Thing"]})
        return base

    def test_shared_output_gets_interface_node_both_depend_on(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan(mod, tmp_path)
        capsys.readouterr()
        mod.cmd_join(base)
        nodes = mod.load_nodes(base)
        assert nodes["interface-thing"]["outputs"] == ["Thing"]
        assert nodes["maker"]["depends"] == ["interface-thing"]
        assert nodes["user"]["depends"] == ["interface-thing"]
        assert capsys.readouterr().out == (
            "maker depends on interface-thing\nuser depends on interface-thing\n"
        )

    def test_existing_depends_edge_is_kept(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = self._plan(mod, tmp_path)
        mod.edit_links(base, "user", {"depends": ["maker"]}, add=True)
        mod.cmd_join(base)
        assert mod.load_nodes(base)["user"]["depends"] == ["maker", "interface-thing"]

    def test_rerun_prints_nothing_to_join(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan(mod, tmp_path)
        mod.cmd_join(base)
        capsys.readouterr()
        mod.cmd_join(base)
        assert capsys.readouterr().out == "nothing to join\n"

    def test_duplicate_producer_errors(self, mod: ModuleType, tmp_path: Path) -> None:
        base = self._plan(mod, tmp_path)
        mod.cmd_add(base, "rival", {"outputs": ["Thing"]})
        with pytest.raises(mod.FocusError) as exc_info:
            mod.cmd_join(base)
        assert exc_info.value.problems == ["'Thing': output of maker, rival"]

    def test_deleter_depends_on_each_consumer(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = self._plan(mod, tmp_path)
        mod.cmd_add(base, "cleaner", {"deletes": ["Thing"]})
        capsys.readouterr()
        mod.cmd_join(base)
        assert mod.load_nodes(base)["cleaner"]["depends"] == ["user"]
        assert "cleaner after user (deletes 'Thing')\n" in capsys.readouterr().out

    def test_consumer_depending_on_deleter_is_a_cycle(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = self._plan(mod, tmp_path)
        mod.cmd_add(base, "cleaner", {"deletes": ["Thing"]})
        mod.edit_links(base, "user", {"depends": ["cleaner"]}, add=True)
        with pytest.raises(mod.FocusError) as exc_info:
            mod.cmd_join(base)
        assert any("dependency cycle" in p for p in exc_info.value.problems)


class TestSiblingDepends:
    """Tests for depends entries naming a node in a sibling plan dir."""

    def _plans(self, mod: ModuleType, tmp_path: Path) -> tuple[Path, Path]:
        core, app = tmp_path / "core", tmp_path / "app"
        mod.cmd_init(core)
        mod.cmd_init(app)
        mod.cmd_add(core, "port", {})
        mod.cmd_add(app, "widget", {"depends": ["core/port"]})
        return core, app

    def test_ready_waits_until_sibling_node_is_done(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        core, app = self._plans(mod, tmp_path)
        plan = mod.plan_path(app)
        sections = mod.parse_sections(plan.read_text())
        sections["Checks"] = "- true"
        plan.write_text(mod.render_plan(app.name, sections))
        mod.cmd_set_test(app, "widget", "true")
        capsys.readouterr()
        with pytest.raises(SystemExit):
            mod.cmd_ready(app, "widget")
        assert capsys.readouterr().out == "waiting on: core/port\n"
        mod.cmd_built(core, "port")
        mod.cmd_pass(core, "port")
        capsys.readouterr()
        mod.cmd_ready(app, "widget")
        assert capsys.readouterr().out == "ready\n"

    def test_waves_count_sibling_dependencies(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        core, app = self._plans(mod, tmp_path)
        mod.cmd_add(app, "gadget", {})
        capsys.readouterr()
        mod.cmd_waves(app)
        assert capsys.readouterr().out == (
            "### Wave 1\n- [ ] gadget (ready)\n\n### Wave 2\n- [ ] widget\n"
        )
        mod.cmd_built(core, "port")
        mod.cmd_pass(core, "port")
        capsys.readouterr()
        mod.cmd_waves(app)
        assert "- [ ] widget (ready)" in capsys.readouterr().out

    def test_graph_draws_sibling_dependency_with_safe_id(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        _, app = self._plans(mod, tmp_path)
        graph = mod.parse_sections(mod.plan_path(app).read_text())["Graph"]
        assert 'core_port["core/port"] --> widget["widget"]' in graph

    def test_briefs_include_sibling_dependency_out(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        core, app = self._plans(mod, tmp_path)
        port_path = mod.node_path(core, "port", "todo")
        port_path.write_text(
            port_path.read_text().replace("## Out\n", "## Out\n\n- make_port()\n")
        )
        capsys.readouterr()
        mod.cmd_briefs(app)
        nodes = json.loads(capsys.readouterr().out)["nodes"]
        assert "## core/port\n\n- make_port()" in nodes["widget"]

    @pytest.mark.parametrize("remove_dir", [False, True])
    def test_join_reports_missing_sibling_dependency_as_unknown(
        self, mod: ModuleType, tmp_path: Path, remove_dir: bool
    ) -> None:
        core, app = self._plans(mod, tmp_path)
        if remove_dir:
            shutil.rmtree(core)
        else:
            mod.cmd_remove(core, "port")
        with pytest.raises(mod.FocusError) as exc_info:
            mod.cmd_join(app)
        assert exc_info.value.problems == ["widget: unknown dependency 'core/port'"]

    def test_cycle_across_dirs_errors(self, mod: ModuleType, tmp_path: Path) -> None:
        core, _ = self._plans(mod, tmp_path)
        with pytest.raises(mod.FocusError) as exc_info:
            mod.edit_links(core, "port", {"depends": ["app/widget"]}, add=True)
        assert exc_info.value.problems == [
            "dependency cycle: port -> app/widget -> port"
        ]

    def test_rename_keeps_same_dir_references(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        _, app = self._plans(mod, tmp_path)
        mod.cmd_add(app, "gadget", {"depends": ["widget"]})
        mod.cmd_rename(app, "widget", "gizmo")
        depends = mod.load_nodes(app)["gadget"]["depends"]
        assert depends == ["gizmo"]
        assert mod.load_nodes(app)["gizmo"]["depends"] == ["core/port"]

    def test_waves_treat_missing_sibling_dependency_as_not_done(
        self, mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        core, app = self._plans(mod, tmp_path)
        mod.cmd_remove(core, "port")
        capsys.readouterr()
        mod.cmd_waves(app)
        assert capsys.readouterr().out == "### Wave 1\n- [ ] widget\n"


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
        mod.cmd_add(base, "widget", {})
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
        mod.cmd_add(base, "widget", {})
        monkeypatch.setattr(
            sys, "argv", ["focus", "rename", str(base), "widget", "gadget"]
        )
        mod.main()
        assert mod.node_path(base, "gadget", "todo").exists()

    def test_set_test_via_cli(
        self, mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        monkeypatch.setattr(
            sys, "argv", ["focus", "set-test", str(base), "widget", "pytest -q"]
        )
        mod.main()
        assert "test: pytest -q" in mod.node_path(base, "widget", "todo").read_text()

    def test_start_via_cli(
        self, mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        monkeypatch.setattr(sys, "argv", ["focus", "start", str(base), "widget"])
        mod.main()
        assert mod.node_path(base, "widget", "building").exists()

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

    def test_briefs_via_cli(
        self,
        mod: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "widget", {})
        capsys.readouterr()
        monkeypatch.setattr(sys, "argv", ["focus", "briefs", str(base)])
        mod.main()
        assert list(json.loads(capsys.readouterr().out)["nodes"]) == ["widget"]


class TestWriteAtomic:
    """Tests for atomic file writes."""

    def test_replaces_content_and_leaves_no_temp_file(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        target = tmp_path / "PLAN.md"
        target.write_text("old")
        mod.write_atomic(target, "new")
        assert target.read_text() == "new"
        assert list(tmp_path.iterdir()) == [target]


class TestConcurrentMoves:
    """Tests for parallel node moves on one plan."""

    def test_parallel_built_keeps_hand_written_sections(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        plan = mod.plan_path(base)
        sections = mod.parse_sections(plan.read_text())
        sections["Constraints"] = "- keep it small"
        sections["Checks"] = "- pytest -q"
        plan.write_text(mod.render_plan(base.name, sections))
        names = [f"node{i}" for i in range(12)]
        for name in names:
            mod.cmd_add(base, name, {})
        with ThreadPoolExecutor(len(names)) as pool:
            list(pool.map(lambda name: mod.cmd_built(base, name), names))
        text = plan.read_text()
        assert "- keep it small" in text
        assert "- pytest -q" in text
        assert all(f"{name}:::testing" in text for name in names)


class TestParentDir:
    """Tests for running commands on a dir whose subdirs are plan dirs."""

    @pytest.fixture
    def parent(self, mod: ModuleType, tmp_path: Path) -> Path:
        parent = tmp_path / "plans"
        parent.mkdir()
        mod.plan_path(parent).write_text("# plans\n")
        for name in ("core", "app"):
            mod.cmd_init(parent / name)
        mod.cmd_add(parent / "core", "port", {})
        mod.cmd_add(parent / "app", "widget", {"depends": ["core/port"]})
        return parent

    def _run(
        self, mod: ModuleType, monkeypatch: pytest.MonkeyPatch, *argv: str
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["focus", *argv])
        mod.main()

    def test_node_commands_act_on_the_child_plan(
        self, mod: ModuleType, parent: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._run(mod, monkeypatch, "built", str(parent), "core/port")
        assert mod.node_path(parent / "core", "port", "testing").exists()
        self._run(mod, monkeypatch, "link", str(parent), "app/widget", "--scope", "w/")
        assert (
            "scope: w/" in mod.node_path(parent / "app", "widget", "todo").read_text()
        )

    def test_waves_merge_child_plans(
        self,
        mod: ModuleType,
        parent: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mod.cmd_add(parent / "app", "gadget", {})
        capsys.readouterr()
        self._run(mod, monkeypatch, "waves", str(parent))
        assert capsys.readouterr().out == (
            "### Wave 1\n- [ ] app/gadget (ready)\n- [ ] core/port (ready)\n\n"
            "### Wave 2\n- [ ] app/widget\n"
        )

    def test_briefs_and_comment_merge_child_plans(
        self,
        mod: ModuleType,
        parent: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        capsys.readouterr()
        self._run(mod, monkeypatch, "briefs", str(parent))
        briefs = json.loads(capsys.readouterr().out)
        assert list(briefs["nodes"]) == ["app/widget", "core/port"]
        assert "# app" in briefs["plan"]
        assert "# core" in briefs["plan"]
        out = tmp_path / "out"
        self._run(mod, monkeypatch, "briefs", str(parent), "--out", str(out))
        assert capsys.readouterr().out == f"{out}/app/widget.md\n{out}/core/port.md\n"
        self._run(mod, monkeypatch, "comment", str(parent))
        comment = capsys.readouterr().out
        assert comment.index("### core/port") < comment.index("### app/widget")

    def test_join_and_check_wave_run_over_child_plans(
        self,
        mod: ModuleType,
        parent: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        app = parent / "app"
        mod.cmd_add(app, "gadget", {"outputs": ["api"]})
        mod.cmd_add(app, "gizmo", {"inputs": ["api"]})
        capsys.readouterr()
        self._run(mod, monkeypatch, "join", str(parent))
        assert capsys.readouterr().out == (
            "app/gadget depends on app/interface-api\n"
            "app/gizmo depends on app/interface-api\n"
        )
        self._run(mod, monkeypatch, "join", str(parent))
        assert capsys.readouterr().out == "nothing to join\n"
        for name, check in (("app", "true"), ("core", "false")):
            plan = mod.plan_path(parent / name)
            sections = mod.parse_sections(plan.read_text())
            sections["Checks"] = f"- {check}"
            plan.write_text(mod.render_plan(name, sections))
        capsys.readouterr()
        with pytest.raises(SystemExit):
            self._run(mod, monkeypatch, "check-wave", str(parent))
        assert capsys.readouterr().out == "$ true\n$ false\n`false` exited 1\n"


class TestView:
    """Tests for the view command's graph data and server."""

    @pytest.fixture
    def parent(self, mod: ModuleType, tmp_path: Path) -> Path:
        parent = tmp_path / "plans"
        parent.mkdir()
        mod.plan_path(parent).write_text("# plans\n")
        for name in ("core", "app"):
            mod.cmd_init(parent / name)
        mod.cmd_add(parent / "core", "port", {})
        mod.node_path(parent / "core", "port", "todo").write_text(
            mod.render_node_file(
                {}, "# port\n\n## In\n\n- a\n\n## Out\n\n- b\n\n## Accept\n\n- c\n"
            )
        )
        mod.cmd_add(parent / "app", "widget", {"depends": ["core/port"]})
        return parent

    def _serve(self, mod: ModuleType, base: Path) -> tuple[ThreadingHTTPServer, str]:
        server = mod.make_view_server(base, 0)
        threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        return server, f"http://127.0.0.1:{server.server_port}"

    def test_data_for_parent_of_plan_dirs(self, mod: ModuleType, parent: Path) -> None:
        data = mod.view_data(parent)
        assert data["repos"] == ["app", "core"]
        assert data["waves"] == 2
        nodes = {node["id"]: node for node in data["nodes"]}
        assert nodes["core/port"] == {
            "id": "core/port",
            "repo": "core",
            "label": "port",
            "wave": 1,
            "stage": "todo",
            "depends": [],
            "sections": {"In": "- a", "Out": "- b", "Accept": "- c"},
        }
        assert nodes["app/widget"]["wave"] == 2
        assert nodes["app/widget"]["depends"] == ["core/port"]

    def test_data_for_single_plan_dir(self, mod: ModuleType, tmp_path: Path) -> None:
        base = tmp_path / "plan"
        mod.cmd_init(base)
        mod.cmd_add(base, "port", {})
        mod.cmd_add(base, "widget", {"depends": ["port"]})
        data = mod.view_data(base)
        assert data["repos"] == ["plan"]
        nodes = {node["id"]: node for node in data["nodes"]}
        assert nodes["widget"]["repo"] == "plan"
        assert nodes["widget"]["label"] == "widget"
        assert nodes["widget"]["wave"] == 2

    def test_data_reports_stage(self, mod: ModuleType, parent: Path) -> None:
        mod.cmd_built(parent / "core", "port")
        nodes = {node["id"]: node for node in mod.view_data(parent)["nodes"]}
        assert nodes["core/port"]["stage"] == "testing"

    def test_data_reports_building_stage(self, mod: ModuleType, parent: Path) -> None:
        mod.cmd_start(parent / "core", "port")
        nodes = {node["id"]: node for node in mod.view_data(parent)["nodes"]}
        assert nodes["core/port"]["stage"] == "building"

    def test_server_serves_fresh_data_and_page(
        self, mod: ModuleType, parent: Path
    ) -> None:
        server, url = self._serve(mod, parent)
        try:
            with urllib.request.urlopen(f"{url}/data.json") as response:
                assert response.headers["Content-Type"] == "application/json"
                assert len(json.loads(response.read())["nodes"]) == 2
            mod.cmd_add(parent / "app", "gadget", {})
            with urllib.request.urlopen(f"{url}/data.json") as response:
                assert len(json.loads(response.read())["nodes"]) == 3
            with urllib.request.urlopen(f"{url}/") as response:
                assert b"<html" in response.read()
            with pytest.raises(urllib.error.HTTPError, match="404"):
                urllib.request.urlopen(f"{url}/missing")
        finally:
            server.shutdown()
            server.server_close()

    def test_view_command_requires_a_plan(
        self, mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["focus", "view", str(tmp_path)])
        with pytest.raises(SystemExit):
            mod.main()
