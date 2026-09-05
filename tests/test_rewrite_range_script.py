"""Tests for the git-tidy skill's declarative-plan rebase script."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest
from conftest import FakeSubprocess

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "shared"
    / "skills"
    / "git-tidy"
    / "rewrite_range.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rewrite_range", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod() -> ModuleType:
    """Load the rewrite_range script as a module."""
    return _load()


class TestBuildSequenceScript:
    """Tests for the plan-to-rebase-todo translation."""

    def test_todo_lines_follow_plan_order_and_verbs(
        self, mod: ModuleType, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        plan = [
            {"sha": "b1", "verb": "pick"},
            {"sha": "c1", "verb": "pick"},
            {"sha": "a1", "verb": "pick"},
            {"sha": "d1", "verb": "drop"},
        ]
        fake_subprocess.on("log", "-1", "--format=%s", "b1", stdout="feat: B\n")
        fake_subprocess.on("log", "-1", "--format=%s", "c1", stdout="feat: C\n")
        fake_subprocess.on("log", "-1", "--format=%s", "a1", stdout="feat: A\n")
        fake_subprocess.on("log", "-1", "--format=%s", "d1", stdout="fix: fixup two\n")

        script_path = tmp_path / "seq.sh"
        mod.build_sequence_script(plan, script_path)

        content = script_path.read_text()
        todo = content.split("RESCRIPT_TIDY_EOF'\n", 1)[1].rsplit(
            "RESCRIPT_TIDY_EOF\n", 1
        )[0]
        assert todo.splitlines() == [
            "pick b1 feat: B",
            "pick c1 feat: C",
            "pick a1 feat: A",
            "drop d1 fix: fixup two",
        ]


class TestBuildMessageScript:
    """Tests for the plan-to-message-editor translation."""

    def test_queues_custom_message(self, mod: ModuleType, tmp_path: Path) -> None:
        plan = [
            {"sha": "base", "verb": "pick"},
            {
                "sha": "fixup",
                "verb": "squash",
                "message": "feat: base feature with fixup",
            },
        ]
        script_path = tmp_path / "msg.sh"

        mod.build_message_script(plan, script_path)

        queue_dir = script_path.with_suffix(".queue.d")
        assert (queue_dir / "1.txt").read_text() == "feat: base feature with fixup"

    def test_without_message_keeps_default(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        plan = [
            {"sha": "base", "verb": "pick"},
            {"sha": "fixup", "verb": "squash"},
        ]
        script_path = tmp_path / "msg.sh"

        mod.build_message_script(plan, script_path)

        assert script_path.read_text() == "#!/bin/bash\ntrue\n"


class TestMain:
    """Tests for the CLI entrypoint's wiring into git rebase."""

    def test_wiring_runs_rebase_with_editor_scripts(
        self, mod: ModuleType, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps([{"sha": "abc123", "verb": "pick"}]))

        fake_subprocess.on("rev-parse", "--abbrev-ref", "@{u}", stdout="origin/main\n")
        fake_subprocess.on("log", "-1", "--format=%s", stdout="feat: base feature\n")

        captured: dict[str, Path] = {}

        def _capture_env(argv: list[str], kwargs: dict[str, Any]) -> None:
            env = kwargs["env"]
            captured["seq"] = Path(env["GIT_SEQUENCE_EDITOR"])
            captured["msg"] = Path(env["GIT_EDITOR"])
            assert captured["seq"].exists()
            assert captured["msg"].exists()

        fake_subprocess.on("rebase", "-i", returncode=3, side_effect=_capture_env)

        with (
            patch("sys.argv", ["rewrite_range.py", str(plan_path)]),
            pytest.raises(SystemExit) as exc,
        ):
            mod.main()

        assert exc.value.code == 3
        assert fake_subprocess.matching("rebase", "-i") == [
            ["git", "rebase", "-i", "origin/main"]
        ]
        assert captured["seq"].name == "sequence_editor.sh"
        assert captured["msg"].name == "message_editor.sh"

    def test_invalid_verb_rejected(self, mod: ModuleType, tmp_path: Path) -> None:
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps([{"sha": "abc123", "verb": "bogus"}]))

        with (
            patch("sys.argv", ["rewrite_range.py", str(plan_path)]),
            pytest.raises(ValueError, match="invalid verb"),
        ):
            mod.main()
