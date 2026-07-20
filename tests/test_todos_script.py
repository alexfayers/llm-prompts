"""Tests for the todos skill's scan script."""

from __future__ import annotations

import importlib.util
import json
import subprocess
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
    / "todos"
    / "find_todos.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("find_todos", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod() -> ModuleType:
    """Load the find_todos script as a module."""
    return _load()


class TestScanFile:
    """Tests for marker detection within a single file."""

    def test_finds_todo_comment(self, mod: ModuleType, tmp_path: Path) -> None:
        target = tmp_path / "a.py"
        target.write_text("# TODO: fix null case\n")
        hits = mod.scan_file(target, tmp_path)
        assert len(hits) == 1
        assert hits[0]["type"] == "TODO"
        assert hits[0]["task"] == "fix null case"

    def test_detects_all_marker_types(self, mod: ModuleType, tmp_path: Path) -> None:
        target = tmp_path / "a.py"
        target.write_text(
            "# FIXME: retry logic\n"
            "# HACK: workaround for flaky test\n"
            "# XXX: revisit this\n"
            "# BUG: off by one\n"
            "# this is just prose, not a marker\n"
        )
        hits = mod.scan_file(target, tmp_path)
        assert [h["type"] for h in hits] == ["FIXME", "HACK", "XXX", "BUG"]

    def test_reports_correct_line_number(self, mod: ModuleType, tmp_path: Path) -> None:
        target = tmp_path / "a.py"
        target.write_text("first line\nsecond line\n# TODO: on line three\n")
        hits = mod.scan_file(target, tmp_path)
        assert hits[0]["line"] == 3

    def test_strips_task_text(self, mod: ModuleType, tmp_path: Path) -> None:
        target = tmp_path / "a.py"
        target.write_text(
            "# TODO(alex): revisit ownership\n# TODO - dash separated task\n"
        )
        hits = mod.scan_file(target, tmp_path)
        assert hits[0]["task"] == "alex): revisit ownership"
        assert hits[1]["task"] == "dash separated task"

    def test_unreadable_file_does_not_crash(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        target = tmp_path / "bad.bin"
        target.write_bytes(b"\xff\xfe\x00TODO: garbage bytes\x00\xff")
        hits = mod.scan_file(target, tmp_path)
        assert isinstance(hits, list)


class TestListFiles:
    """Tests for tree walking and directory exclusion."""

    def test_excludes_vendor_dirs(self, mod: ModuleType, tmp_path: Path) -> None:
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "x.js").write_text("// TODO: vendored\n")
        (tmp_path / "app.py").write_text("# TODO: real code\n")
        files = mod.list_files(tmp_path)
        names = {f.name for f in files}
        assert names == {"app.py"}

    def test_excludes_hidden_dirs(self, mod: ModuleType, tmp_path: Path) -> None:
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "x.py").write_text("# TODO: hidden\n")
        (tmp_path / "app.py").write_text("# TODO: real code\n")
        files = mod.list_files(tmp_path)
        names = {f.name for f in files}
        assert names == {"app.py"}


class TestFindTodos:
    """Tests for the end-to-end scan wiring."""

    def test_no_todos_returns_empty(self, mod: ModuleType, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("print('hello')\n")
        result = mod.find_todos(tmp_path)
        assert result["todos"] == []

    def test_collects_todo_md_paths(self, mod: ModuleType, tmp_path: Path) -> None:
        (tmp_path / "TODO.md").write_text("- [ ] ship it\n")
        result = mod.find_todos(tmp_path)
        assert result["todo_files"] == ["TODO.md"]

    def test_paths_relative_to_root(self, mod: ModuleType, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "a.py").write_text("# TODO: nested\n")
        result = mod.find_todos(tmp_path)
        assert result["todos"][0]["file"] == "sub/a.py"


class TestMain:
    """Tests for the CLI entrypoint."""

    def test_prints_json_for_root_arg(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("# TODO: cli check\n")
        completed = subprocess.run(
            [sys.executable, str(_SCRIPT), str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(completed.stdout)
        assert result["todos"][0]["task"] == "cli check"

    def test_defaults_to_current_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("# TODO: default root\n")
        completed = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            capture_output=True,
            text=True,
            check=True,
            cwd=tmp_path,
        )
        result = json.loads(completed.stdout)
        assert result["todos"][0]["task"] == "default root"
