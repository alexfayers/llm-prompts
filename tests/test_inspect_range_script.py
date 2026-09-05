"""Tests for the git-tidy skill's commit-range safety-gate script."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
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
    / "inspect_range.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("inspect_range", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod() -> ModuleType:
    """Load the inspect_range script as a module."""
    return _load()


def _run_main(
    mod: ModuleType, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, dict[str, object]]:
    with (
        patch("sys.argv", ["inspect_range.py", *args]),
        pytest.raises(SystemExit) as exc,
    ):
        mod.main()
    return exc.value.code, json.loads(capsys.readouterr().out)


class TestMain:
    """Tests for the CLI entrypoint against real git repos."""

    def test_clean_unpushed_range_is_safe(
        self, mod: ModuleType, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_subprocess.on("status", "--porcelain", stdout="")
        fake_subprocess.on("rev-parse", "--abbrev-ref", "@{u}", stdout="origin/main\n")
        fake_subprocess.on(
            "log",
            "--reverse",
            stdout=fake_subprocess.sha_subjects(("abc123", "first"), ("def456", "second")),
        )
        fake_subprocess.on("rev-list", "--min-parents=2", stdout="")
        fake_subprocess.on_match(lambda argv: "^@{u}" in argv, stdout="abc123\ndef456\n")
        fake_subprocess.on("rev-list", stdout="abc123\ndef456\n")

        code, result = _run_main(mod, capsys)

        assert code == 0
        assert result["safe_to_rewrite"] is True
        assert result["commit_count"] == 2
        assert result["has_merge_commits"] is False
        assert result["working_tree_dirty"] is False

    def test_dirty_working_tree_is_unsafe(
        self, mod: ModuleType, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_subprocess.on("status", "--porcelain", stdout=" M a.txt\n")
        fake_subprocess.on("rev-parse", "--abbrev-ref", "@{u}", stdout="origin/main\n")
        fake_subprocess.on(
            "log", "--reverse", stdout=fake_subprocess.sha_subjects(("abc123", "first"))
        )
        fake_subprocess.on("rev-list", "--min-parents=2", stdout="")
        fake_subprocess.on_match(lambda argv: "^@{u}" in argv, stdout="abc123\n")
        fake_subprocess.on("rev-list", stdout="abc123\n")

        code, result = _run_main(mod, capsys)

        assert code == 1
        assert result["safe_to_rewrite"] is False
        assert result["working_tree_dirty"] is True

    def test_merge_commit_in_range_is_unsafe(
        self, mod: ModuleType, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_subprocess.on("status", "--porcelain", stdout="")
        fake_subprocess.on("rev-parse", "--abbrev-ref", "@{u}", stdout="origin/main\n")
        fake_subprocess.on(
            "log",
            "--reverse",
            stdout=fake_subprocess.sha_subjects(
                ("abc123", "feature work"), ("def456", "merge feature")
            ),
        )
        fake_subprocess.on("rev-list", "--min-parents=2", stdout="def456\n")
        fake_subprocess.on_match(lambda argv: "^@{u}" in argv, stdout="abc123\ndef456\n")
        fake_subprocess.on("rev-list", stdout="abc123\ndef456\n")

        code, result = _run_main(mod, capsys)

        assert code == 1
        assert result["safe_to_rewrite"] is False
        assert result["has_merge_commits"] is True

    def test_explicit_base_including_pushed_commit_is_unsafe(
        self, mod: ModuleType, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_subprocess.on("status", "--porcelain", stdout="")
        fake_subprocess.on(
            "log",
            "--reverse",
            stdout=fake_subprocess.sha_subjects(
                ("abc123", "pushed commit"), ("def456", "unpushed commit")
            ),
        )
        fake_subprocess.on("rev-list", "--min-parents=2", stdout="")
        fake_subprocess.on_match(lambda argv: "^@{u}" in argv, stdout="def456\n")
        fake_subprocess.on("rev-list", stdout="abc123\ndef456\n")

        code, result = _run_main(mod, capsys, "root")

        assert code == 1
        assert result["safe_to_rewrite"] is False
        assert result["has_pushed_commits"] is True

    def test_no_upstream_falls_back_to_root(
        self, mod: ModuleType, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_subprocess.on("status", "--porcelain", stdout="")
        fake_subprocess.on("rev-parse", "--abbrev-ref", "@{u}", returncode=128)
        fake_subprocess.on(
            "log",
            "--reverse",
            stdout=fake_subprocess.sha_subjects(("abc123", "first"), ("def456", "second")),
        )
        fake_subprocess.on("rev-list", "--min-parents=2", stdout="")
        fake_subprocess.on_match(lambda argv: "^@{u}" in argv, stdout="abc123\ndef456\n")
        fake_subprocess.on("rev-list", stdout="abc123\ndef456\n")

        code, result = _run_main(mod, capsys)

        assert code == 0
        assert result["safe_to_rewrite"] is True
        assert result["commit_count"] == 2
        assert result["base"] == "--root"

    def test_no_commits_exits_with_no_resolvable_base(
        self, mod: ModuleType, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_subprocess.on("status", "--porcelain", stdout="")
        fake_subprocess.on("rev-parse", "--abbrev-ref", "@{u}", returncode=128)
        fake_subprocess.on("log", "--reverse", returncode=128)

        code, _ = _run_main(mod, capsys)

        assert code == 2
