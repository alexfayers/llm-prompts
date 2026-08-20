"""Tests for the git-usage skill's repo-check script."""

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
    / "git-usage"
    / "check_repos.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_repos", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


@pytest.fixture
def mod() -> ModuleType:
    """Load the check_repos script as a module."""
    return _load()


class TestInspectRepo:
    """Tests for single-repo inspection."""

    def test_clean_repo_reports_nothing(self, mod: ModuleType, tmp_path: Path) -> None:
        repo = tmp_path / "clean"
        _init_repo(repo)
        (repo / "a.txt").write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        entry = mod.inspect_repo(str(repo))
        assert entry["uncommitted"] == []
        assert entry["unpushed"] == []
        assert entry["no_upstream"] is True

    def test_uncommitted_changes_reported(
        self, mod: ModuleType, tmp_path: Path
    ) -> None:
        repo = tmp_path / "dirty"
        _init_repo(repo)
        (repo / "a.txt").write_text("x\n")
        entry = mod.inspect_repo(str(repo))
        assert any("a.txt" in line for line in entry["uncommitted"])

    def test_no_upstream_flagged(self, mod: ModuleType, tmp_path: Path) -> None:
        repo = tmp_path / "noupstream"
        _init_repo(repo)
        (repo / "a.txt").write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        entry = mod.inspect_repo(str(repo))
        assert entry["no_upstream"] is True

    def test_unpushed_commits_reported(self, mod: ModuleType, tmp_path: Path) -> None:
        upstream = tmp_path / "upstream.git"
        upstream.mkdir()
        _git(upstream, "init", "-q", "--bare")
        repo = tmp_path / "local"
        _init_repo(repo)
        (repo / "a.txt").write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        _git(repo, "remote", "add", "origin", str(upstream))
        _git(repo, "push", "-q", "-u", "origin", "HEAD")
        (repo / "b.txt").write_text("y\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "second commit")
        entry = mod.inspect_repo(str(repo))
        assert entry["no_upstream"] is False
        assert any("second commit" in line for line in entry["unpushed"])


class TestCheckRepos:
    """Tests for the clean flag aggregation (source repos stubbed out for isolation)."""

    def test_clean_flag_true_when_all_clean(
        self, mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "source_paths", list)
        repo = tmp_path / "clean"
        _init_repo(repo)
        (repo / "a.txt").write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "init")
        result = mod.check_repos(repo)
        assert result["clean"] is True

    def test_clean_flag_false_when_dirty(
        self, mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mod, "source_paths", list)
        repo = tmp_path / "dirty"
        _init_repo(repo)
        (repo / "a.txt").write_text("x\n")
        result = mod.check_repos(repo)
        assert result["clean"] is False


class TestMain:
    """Tests for the CLI entrypoint and exit-code gate."""

    def test_exit_nonzero_when_dirty(self, tmp_path: Path) -> None:
        repo = tmp_path / "dirty"
        _init_repo(repo)
        (repo / "a.txt").write_text("x\n")
        completed = subprocess.run(
            [sys.executable, str(_SCRIPT), "--workspace", str(repo)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 1
        result = json.loads(completed.stdout)
        assert result["clean"] is False
