"""Tests for the git-usage skill's repo-check script."""

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
    / "git-usage"
    / "check_repos.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_repos", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod() -> ModuleType:
    """Load the check_repos script as a module."""
    return _load()


class TestInspectRepo:
    """Tests for single-repo inspection."""

    def test_clean_repo_reports_nothing(
        self, fake_subprocess: FakeSubprocess, mod: ModuleType, tmp_path: Path
    ) -> None:
        repo = str(tmp_path / "clean")
        fake_subprocess.on(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", repo=repo, returncode=1
        )
        entry = mod.inspect_repo(repo)
        assert entry["uncommitted"] == []
        assert entry["unpushed"] == []
        assert entry["no_upstream"] is True

    def test_uncommitted_changes_reported(
        self, fake_subprocess: FakeSubprocess, mod: ModuleType, tmp_path: Path
    ) -> None:
        repo = str(tmp_path / "dirty")
        fake_subprocess.on("status", "--porcelain", repo=repo, stdout=" M a.txt\n")
        entry = mod.inspect_repo(repo)
        assert any("a.txt" in line for line in entry["uncommitted"])

    def test_no_upstream_flagged(
        self, fake_subprocess: FakeSubprocess, mod: ModuleType, tmp_path: Path
    ) -> None:
        repo = str(tmp_path / "noupstream")
        fake_subprocess.on(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", repo=repo, returncode=1
        )
        entry = mod.inspect_repo(repo)
        assert entry["no_upstream"] is True

    def test_unpushed_commits_reported(
        self, fake_subprocess: FakeSubprocess, mod: ModuleType, tmp_path: Path
    ) -> None:
        repo = str(tmp_path / "local")
        fake_subprocess.on(
            "log", "--oneline", repo=repo, stdout="abc1234 second commit\n"
        )
        entry = mod.inspect_repo(repo)
        assert entry["no_upstream"] is False
        assert any("second commit" in line for line in entry["unpushed"])


class TestCheckRepos:
    """Tests for the clean flag aggregation (source repos stubbed out for isolation)."""

    def test_clean_flag_true_when_all_clean(
        self,
        fake_subprocess: FakeSubprocess,
        mod: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(mod, "source_paths", list)
        repo = tmp_path / "clean"
        repo.mkdir()
        fake_subprocess.on("rev-parse", "--show-toplevel", repo=repo, stdout=str(repo))
        result = mod.check_repos(repo)
        assert result["clean"] is True

    def test_clean_flag_false_when_dirty(
        self,
        fake_subprocess: FakeSubprocess,
        mod: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(mod, "source_paths", list)
        repo = tmp_path / "dirty"
        repo.mkdir()
        fake_subprocess.on("rev-parse", "--show-toplevel", repo=repo, stdout=str(repo))
        fake_subprocess.on("status", "--porcelain", repo=repo, stdout=" M a.txt\n")
        result = mod.check_repos(repo)
        assert result["clean"] is False


class TestMain:
    """Tests for the CLI entrypoint and exit-code gate."""

    def test_exit_nonzero_when_dirty(
        self,
        fake_subprocess: FakeSubprocess,
        mod: ModuleType,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on(
            "rev-parse", "--show-toplevel", repo=tmp_path, stdout=str(tmp_path)
        )
        fake_subprocess.on("status", "--porcelain", repo=tmp_path, stdout=" M a.txt\n")
        with (
            patch("sys.argv", ["check_repos", "--workspace", str(tmp_path)]),
            pytest.raises(SystemExit) as exc,
        ):
            mod.main()
        assert exc.value.code == 1
        result = json.loads(capsys.readouterr().out)
        assert result["clean"] is False
