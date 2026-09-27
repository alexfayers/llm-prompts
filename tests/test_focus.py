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
