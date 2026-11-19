"""Tests for the opencode install target."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import FakeSubprocess, run_capturing_exit

from llm_prompts.cli import main
from llm_prompts.install import (
    _opencode_config_dir,
    get_managed_dirs,
    try_install_hooks_opencode,
    try_install_memory_opencode,
)
from llm_prompts.install import main as install_main

pytestmark = pytest.mark.usefixtures("bare_tree")


@pytest.fixture(autouse=True)
def _no_config_dir_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


@pytest.fixture
def opencode_home(tmp_path: Path) -> Iterator[Path]:
    """Run `install opencode` into a fake home with overlays redirected."""
    home = tmp_path / "home"
    home.mkdir()
    with (
        patch("llm_prompts.install.Path.home", return_value=home),
        patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
    ):
        install_main(["opencode"])
        yield home


class TestOpencodeInstallLayout:
    def test_rules_land_in_single_agents_md(self, opencode_home: Path) -> None:
        config = opencode_home / ".config" / "opencode"
        assert (config / "AGENTS.md").is_file()
        assert not (config / "rules").exists()

    @pytest.mark.usefixtures("core_tree")
    def test_skills_materialize_into_opencode_skills(self, opencode_home: Path) -> None:
        skills = opencode_home / ".config" / "opencode" / "skills"
        assert (skills / "tdd").is_dir() and not (skills / "tdd").is_symlink()


class TestOpencodeManagedDirs:
    def test_includes_skills_not_bare_opencode_config(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            managed = set(get_managed_dirs())

        assert home / ".config" / "opencode" / "skills" in managed
        assert home / ".config" / "opencode" not in managed


class TestOpencodeConfigDir:
    @pytest.mark.parametrize(
        ("env", "expected"),
        [
            ({"OPENCODE_CONFIG_DIR": "oc", "XDG_CONFIG_HOME": "xdg"}, "oc"),
            ({"XDG_CONFIG_HOME": "xdg"}, "xdg/opencode"),
        ],
        ids=["opencode-config-dir", "xdg-config-home"],
    )
    def test_honours_opencode_config_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        env: dict[str, str],
        expected: str,
    ) -> None:
        for name, value in env.items():
            monkeypatch.setenv(name, str(tmp_path / value))

        assert _opencode_config_dir() == tmp_path / expected


class TestOpencodeToolInstalls:
    def test_memory_installs_for_opencode(
        self,
        fake_subprocess: FakeSubprocess,
        venv_and_user_bins: tuple[Path, Path],
    ) -> None:
        _, user_bin = venv_and_user_bins

        binary = str(user_bin / "mcp-memory")

        with patch("llm_prompts.install._memory_service_exists", return_value=False):
            try_install_memory_opencode()

        assert fake_subprocess.commands == [
            [binary, "install", "opencode"],
            [binary, "setup-service"],
        ]

    def test_hooks_install_for_opencode(
        self,
        fake_subprocess: FakeSubprocess,
        venv_and_user_bins: tuple[Path, Path],
    ) -> None:
        _, user_bin = venv_and_user_bins

        try_install_hooks_opencode()

        assert fake_subprocess.commands == [
            [str(user_bin / "cline-hook"), "install", "opencode"]
        ]

    def test_nothing_runs_without_a_user_wide_binary(
        self,
        fake_subprocess: FakeSubprocess,
        venv_and_user_bins: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        venv_bin, _ = venv_and_user_bins
        monkeypatch.setenv("PATH", str(venv_bin))

        try_install_hooks_opencode()
        try_install_memory_opencode()

        assert fake_subprocess.commands == []

    def test_install_command_sets_up_hooks_and_memory(self) -> None:
        with (
            patch("sys.argv", ["llm-prompts", "install", "opencode", "--no-update"]),
            patch("llm_prompts.install.main", return_value=False),
            patch("llm_prompts.install.try_install_hooks_opencode") as hooks,
            patch("llm_prompts.install.try_install_memory_opencode") as memory,
        ):
            exit_code = run_capturing_exit(main)

        assert exit_code in (0, None)
        hooks.assert_called_once_with()
        memory.assert_called_once_with()
