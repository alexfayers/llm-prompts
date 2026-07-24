"""Tests for the tidy-code skill's net-reduction gate script."""

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
    / "tidy-code"
    / "check_reduction.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_reduction", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod() -> ModuleType:
    """Load the check_reduction script as a module."""
    return _load()


class TestParseNumstat:
    """Tests for summing added/removed counts from numstat output."""

    def test_sums_across_files(self, mod: ModuleType) -> None:
        added, removed = mod.parse_numstat("3\t7\ta.py\n1\t2\tb.py\n")
        assert (added, removed) == (4, 9)

    def test_skips_binary_files(self, mod: ModuleType) -> None:
        added, removed = mod.parse_numstat("-\t-\timg.png\n5\t1\ta.py\n")
        assert (added, removed) == (5, 1)

    def test_empty_output_is_zero(self, mod: ModuleType) -> None:
        assert mod.parse_numstat("") == (0, 0)


class TestEvaluate:
    """Tests for the threshold-band classification."""

    def test_net_negative_passes(self, mod: ModuleType) -> None:
        result = mod.evaluate(added=2, removed=10)
        assert result["net"] == -8
        assert result["pass"] is True

    def test_neutral_band_passes(self, mod: ModuleType) -> None:
        result = mod.evaluate(added=8, removed=5)
        assert result["net"] == 3
        assert result["pass"] is True

    def test_boundary_plus_five_passes(self, mod: ModuleType) -> None:
        result = mod.evaluate(added=5, removed=0)
        assert result["pass"] is True

    def test_beyond_band_fails(self, mod: ModuleType) -> None:
        result = mod.evaluate(added=6, removed=0)
        assert result["net"] == 6
        assert result["pass"] is False


class TestMain:
    """Tests for the CLI entrypoint against a real git repo."""

    def _git(self, repo: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        )

    def _init_repo(self, repo: Path) -> None:
        self._git(repo, "init")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "test")
        (repo / "f.txt").write_text("a\nb\nc\nd\ne\n")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-m", "init")

    def test_net_negative_diff_exits_zero(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)
        (tmp_path / "f.txt").write_text("a\n")
        completed = subprocess.run(
            [sys.executable, str(_SCRIPT)], cwd=tmp_path, capture_output=True, text=True
        )
        result = json.loads(completed.stdout)
        assert result["pass"] is True
        assert completed.returncode == 0

    def test_net_positive_diff_exits_one(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)
        (tmp_path / "f.txt").write_text("a\nb\nc\nd\ne\n" + "x\n" * 10)
        completed = subprocess.run(
            [sys.executable, str(_SCRIPT)], cwd=tmp_path, capture_output=True, text=True
        )
        result = json.loads(completed.stdout)
        assert result["pass"] is False
        assert completed.returncode == 1
