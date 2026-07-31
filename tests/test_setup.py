"""Tests for setup overlay/standalone inference across local and remote sources."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from llm_prompts import setup


@pytest.fixture(autouse=True)
def _clear_fetch_cache() -> None:
    """Reset the lru_cache on the real remote fetch before each test."""
    setup._fetch_remote_pyproject.cache_clear()


class TestReadPyproject:
    def test_local_valid(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\n', encoding="utf-8"
        )
        data = setup._read_pyproject({"name": "x", "source": str(tmp_path)})
        assert data == {"project": {"name": "x"}}

    def test_local_missing(self, tmp_path: Path) -> None:
        assert setup._read_pyproject({"name": "x", "source": str(tmp_path)}) is None

    def test_local_malformed(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("not = = valid [[[", encoding="utf-8")
        assert setup._read_pyproject({"name": "x", "source": str(tmp_path)}) is None

    def test_git_source_uses_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        canned = {"project": {"name": "remote"}}
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", lambda url: canned)
        data = setup._read_pyproject(
            {"name": "x", "source": "git+https://github.com/user/repo.git"}
        )
        assert data == canned

    def test_bare_pypi_never_fetches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock = MagicMock()
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", mock)
        assert setup._read_pyproject({"name": "x", "source": "some-package"}) is None
        mock.assert_not_called()


class TestFetchRemotePyproject:
    def test_git_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("llm_prompts.setup.shutil.which", return_value=None):
            assert setup._fetch_remote_pyproject("https://x/repo.git") is None
        assert "git not available" in capsys.readouterr().err

    def test_clone_non_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("llm_prompts.setup.shutil.which", return_value="/usr/bin/git"):
            with patch(
                "llm_prompts.setup.subprocess.run",
                return_value=MagicMock(returncode=1),
            ):
                assert setup._fetch_remote_pyproject("https://x/repo.git") is None
        assert "could not clone" in capsys.readouterr().err

    def test_clone_timeout(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("llm_prompts.setup.shutil.which", return_value="/usr/bin/git"):
            with patch(
                "llm_prompts.setup.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30),
            ):
                assert setup._fetch_remote_pyproject("https://x/repo.git") is None
        assert "timed out" in capsys.readouterr().err


class TestInferOverlaysFor:
    def test_entry_point_groups(self, monkeypatch: pytest.MonkeyPatch) -> None:
        data: dict[str, Any] = {
            "project": {"entry-points": {"cline_hooks": {}, "llm_prompts": {}}}
        }
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", lambda url: data)
        result = setup._infer_overlays_for(
            {"name": "mcp-memory", "source": "git+https://github.com/user/repo.git"}
        )
        assert sorted(result) == ["cline-hooks", "llm-prompts"]

    def test_own_name_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        data: dict[str, Any] = {"project": {"entry-points": {"cline_hooks": {}}}}
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", lambda url: data)
        result = setup._infer_overlays_for(
            {"name": "cline-hooks", "source": "git+https://github.com/user/repo.git"}
        )
        assert result == []

    def test_no_entry_points(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            setup, "_fetch_remote_pyproject", lambda url: {"project": {}}
        )
        result = setup._infer_overlays_for(
            {"name": "x", "source": "git+https://github.com/user/repo.git"}
        )
        assert result == []

    def test_bare_pypi(self) -> None:
        assert setup._infer_overlays_for({"name": "x", "source": "some-package"}) == []


class TestInferStandalone:
    def test_has_scripts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        data = {"project": {"scripts": {"foo": "pkg:main"}}}
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", lambda url: data)
        assert setup._infer_standalone(
            {"name": "x", "source": "git+https://github.com/user/repo.git"}
        )

    def test_no_scripts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            setup, "_fetch_remote_pyproject", lambda url: {"project": {}}
        )
        assert not setup._infer_standalone(
            {"name": "x", "source": "git+https://github.com/user/repo.git"}
        )

    def test_bare_pypi(self) -> None:
        assert not setup._infer_standalone({"name": "x", "source": "some-package"})


class TestValidatePaths:
    def test_bare_pypi_source_rejected(self) -> None:
        errors = setup._validate_paths(
            [{"name": "x", "source": "some-bare-package-name"}]
        )
        assert len(errors) == 1
        assert "some-bare-package-name" in errors[0]

    def test_git_url_source_ok(self) -> None:
        assert (
            setup._validate_paths(
                [{"name": "x", "source": "git+https://github.com/user/repo.git"}]
            )
            == []
        )

    def test_local_path_source_ok(self, tmp_path: Path) -> None:
        assert setup._validate_paths([{"name": "x", "source": str(tmp_path)}]) == []


class TestBuildCommandsRegression:
    """Regression: git-source tools infer overlays so mcp-memory folds into its targets."""

    def _shipped_tools(self) -> list[dict[str, object]]:
        return tomllib.loads(setup._DEFAULT_CONFIG)["tools"]

    def _canned_pyproject(self, git_url: str) -> dict | None:
        by_repo: dict[str, dict[str, Any]] = {
            "llm-prompts": {
                "project": {
                    "scripts": {"llm-prompts": "llm_prompts.cli:main"},
                    "entry-points": {
                        "cline_hooks": {"llm-prompts": "llm_prompts.hooks"}
                    },
                }
            },
            "cline-hooks": {
                "project": {"scripts": {"cline-hook": "cline_hooks.cli:main"}}
            },
            "mcp-memory": {
                "project": {
                    "entry-points": {
                        "llm_prompts": {"mcp-memory": "mcp_memory"},
                        "cline_hooks": {"mcp-memory": "mcp_memory.hooks"},
                    }
                }
            },
        }
        return next((v for k, v in by_repo.items() if k in git_url), None)

    def test_mcp_memory_folded_as_overlay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(setup, "_fetch_remote_pyproject", self._canned_pyproject)
        commands = setup._build_commands(self._shipped_tools(), "uv")
        overlays_by_core = {
            name: overlay_names for name, _, _, overlay_names in commands
        }

        assert "mcp-memory" not in overlays_by_core
        assert "mcp-memory" in overlays_by_core["llm-prompts"]
        assert "mcp-memory" in overlays_by_core["cline-hooks"]

    def test_fetch_cached_per_url(self) -> None:
        counter = MagicMock(return_value=None)
        with patch("llm_prompts.setup.shutil.which", return_value="/usr/bin/git"):
            with patch("llm_prompts.setup.subprocess.run", counter):
                setup._build_commands(self._shipped_tools(), "uv")
        assert counter.call_count == 3


class TestRunParallelOrdered:
    def test_empty_input_returns_empty_list(self) -> None:
        assert setup._run_parallel_ordered([]) == []

    def test_preserves_submission_order(self) -> None:
        calls = [lambda: ["a"], lambda: ["b"], lambda: ["c"]]
        assert setup._run_parallel_ordered(calls) == [["a"], ["b"], ["c"]]
