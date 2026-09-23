"""Tests for the pi install target."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from llm_prompts.install import get_managed_dirs, uninstall
from llm_prompts.install import main as install_main

_CORE_FRAGMENT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "settings.json"
)


def _install(home: Path, manifest: Path, overlays: list[Path] | None = None) -> None:
    """Run `install pi` into a fake home with overlays and manifest redirected."""
    with (
        patch("llm_prompts.install.Path.home", return_value=home),
        patch(
            "llm_prompts.install._discover_overlay_paths", return_value=overlays or []
        ),
        patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
    ):
        install_main(["pi"])


def _overlay(root: Path, packages: list[str]) -> Path:
    """Build an overlay declaring the given pi packages, returning its prompts dir."""
    fragment = root / "pi" / "settings.json"
    fragment.parent.mkdir(parents=True, exist_ok=True)
    fragment.write_text(json.dumps({"packages": packages}), encoding="utf-8")
    return root


def _settings(home: Path) -> dict[str, Any]:
    """Read pi's global settings from a fake home."""
    path = home / ".pi" / "agent" / "settings.json"
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _core_packages() -> list[str]:
    """Return the packages the core fragment declares."""
    return list(json.loads(_CORE_FRAGMENT.read_text(encoding="utf-8"))["packages"])


@pytest.fixture
def pi_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Install pi into a fake home, yielding it."""
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    _install(home, tmp_path / "installed.json")
    yield home


class TestPiInstallLayout:
    def test_rules_land_in_single_agents_md(self, pi_home: Path) -> None:
        agent_dir = pi_home / ".pi" / "agent"
        assert (agent_dir / "AGENTS.md").is_file()
        assert not (agent_dir / "rules").exists()

    def test_workflows_land_as_prompt_templates(self, pi_home: Path) -> None:
        prompts = pi_home / ".pi" / "agent" / "prompts"
        assert (prompts / "simplify.md").is_file()
        assert (
            not (prompts / "simplify.md").read_text(encoding="utf-8").startswith("---")
        )

    def test_skills_materialize_into_pi_skills(self, pi_home: Path) -> None:
        skills = pi_home / ".pi" / "agent" / "skills"
        assert (skills / "tdd" / "SKILL.md").is_file()
        assert (skills / "git-usage" / "SKILL.md").is_file()

    def test_reinstall_removes_stale_prompt(
        self, pi_home: Path, tmp_path: Path
    ) -> None:
        stray = pi_home / ".pi" / "agent" / "prompts" / "stray.md"
        stray.write_text("stale", encoding="utf-8")
        manifest = tmp_path / "installed.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["agents"]["pi"]["files"].append(str(stray))
        manifest.write_text(json.dumps(data), encoding="utf-8")

        _install(pi_home, manifest)

        assert not stray.exists()


class TestPiAgentDirOverride:
    def test_installs_under_pi_coding_agent_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_dir = tmp_path / "custom-agent"
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))
        home = tmp_path / "home"
        home.mkdir()

        _install(home, tmp_path / "installed.json")

        assert (agent_dir / "AGENTS.md").is_file()
        assert (agent_dir / "prompts" / "simplify.md").is_file()
        assert not (home / ".pi").exists()


class TestPiManagedDirs:
    def test_includes_prompts_and_skills_not_bare_agent_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            managed = set(get_managed_dirs())

        agent_dir = home / ".pi" / "agent"
        assert agent_dir / "prompts" in managed
        assert agent_dir / "skills" in managed
        assert agent_dir not in managed


class TestPiPackages:
    def test_declared_packages_land_in_pi_settings(self, pi_home: Path) -> None:
        assert _settings(pi_home)["packages"] == _core_packages()

    def test_user_settings_and_packages_are_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        settings_path = home / ".pi" / "agent" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        user_entry = {"source": "npm:user-pkg", "extensions": []}
        settings_path.write_text(
            json.dumps({"theme": "dark", "packages": [user_entry]}), encoding="utf-8"
        )

        _install(home, tmp_path / "installed.json")

        settings = _settings(home)
        assert settings["theme"] == "dark"
        assert settings["packages"] == [user_entry, *_core_packages()]

    def test_overlay_packages_are_added_and_dropped_when_undeclared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        overlay = tmp_path / "overlay"

        _install(home, manifest, [_overlay(overlay, ["npm:overlay-pkg"])])
        assert "npm:overlay-pkg" in _settings(home)["packages"]

        _install(home, manifest, [_overlay(overlay, [])])
        assert _settings(home)["packages"] == _core_packages()

    def test_uninstall_removes_only_managed_packages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        _install(home, manifest)
        settings_path = home / ".pi" / "agent" / "settings.json"
        settings = _settings(home)
        settings["packages"].append("npm:user-pkg")
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
        ):
            uninstall(["pi"])

        assert _settings(home)["packages"] == ["npm:user-pkg"]
