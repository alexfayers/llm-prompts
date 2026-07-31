"""Tests for the git-tidy skill's commit-range safety-gate script."""

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
    / "git-tidy"
    / "inspect_range.py"
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "f.txt").write_text("init\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")


def _set_fake_upstream(repo: Path) -> None:
    """Mark the current HEAD as a fake 'origin/main' upstream ref."""
    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "remote", "add", "origin", "/tmp/does-not-exist")
    _git(repo, "update-ref", "refs/remotes/origin/main", head)
    _git(repo, "branch", "--set-upstream-to=origin/main", "main")


def _commit(repo: Path, filename: str, message: str) -> None:
    (repo / filename).write_text(message)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
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


class TestMain:
    """Tests for the CLI entrypoint against real git repos."""

    def test_clean_unpushed_range_is_safe(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _set_fake_upstream(tmp_path)
        _commit(tmp_path, "a.txt", "first")
        _commit(tmp_path, "b.txt", "second")

        completed = _run(tmp_path)
        result = json.loads(completed.stdout)

        assert completed.returncode == 0
        assert result["safe_to_rewrite"] is True
        assert result["commit_count"] == 2
        assert result["has_merge_commits"] is False
        assert result["working_tree_dirty"] is False

    def test_dirty_working_tree_is_unsafe(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _set_fake_upstream(tmp_path)
        _commit(tmp_path, "a.txt", "first")
        (tmp_path / "a.txt").write_text("uncommitted change")

        completed = _run(tmp_path)
        result = json.loads(completed.stdout)

        assert completed.returncode == 1
        assert result["safe_to_rewrite"] is False
        assert result["working_tree_dirty"] is True

    def test_merge_commit_in_range_is_unsafe(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _set_fake_upstream(tmp_path)
        _git(tmp_path, "checkout", "-b", "feature")
        _commit(tmp_path, "feature.txt", "feature work")
        _git(tmp_path, "checkout", "main")
        _commit(tmp_path, "main.txt", "main work")
        _git(tmp_path, "merge", "--no-ff", "-m", "merge feature", "feature")

        completed = _run(tmp_path)
        result = json.loads(completed.stdout)

        assert completed.returncode == 1
        assert result["safe_to_rewrite"] is False
        assert result["has_merge_commits"] is True

    def test_explicit_base_including_pushed_commit_is_unsafe(
        self, tmp_path: Path
    ) -> None:
        _init_repo(tmp_path)
        root = _git(tmp_path, "rev-parse", "HEAD").strip()
        _commit(tmp_path, "pushed.txt", "pushed commit")
        _set_fake_upstream(tmp_path)
        _commit(tmp_path, "unpushed.txt", "unpushed commit")

        completed = _run(tmp_path, root)
        result = json.loads(completed.stdout)

        assert completed.returncode == 1
        assert result["safe_to_rewrite"] is False
        assert result["has_pushed_commits"] is True

    def test_no_upstream_falls_back_to_root(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "a.txt", "second")

        completed = _run(tmp_path)
        result = json.loads(completed.stdout)

        assert completed.returncode == 0
        assert result["safe_to_rewrite"] is True
        assert result["commit_count"] == 2
        assert result["base"] == "--root"

    def test_no_commits_exits_with_no_resolvable_base(self, tmp_path: Path) -> None:
        _git(tmp_path, "init", "-b", "main")
        _git(tmp_path, "config", "user.email", "test@example.com")
        _git(tmp_path, "config", "user.name", "test")

        completed = _run(tmp_path)

        assert completed.returncode == 2
