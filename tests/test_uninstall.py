"""Tests for the uninstall teardown functions in install.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.install import (
    _disallow_update_claude_code,
    _kiro_resources,
    _remove_cline_symlinks,
    _remove_manifest_files,
    _unpatch_kiro_agent_config,
    uninstall,
)
from llm_prompts.install import main as install_main
from llm_prompts.manifest import read_manifest, write_manifest


class TestRemoveManifestFiles:
    def test_removes_files_and_directory(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.md"
        f1.write_text("x", encoding="utf-8")
        d1 = tmp_path / "skills" / "foo"
        d1.mkdir(parents=True)
        (d1 / "SKILL.md").write_text("y", encoding="utf-8")

        _remove_manifest_files("kiro", [str(f1), str(d1)])

        assert not f1.exists()
        assert not d1.exists()

    def test_nonexistent_path_is_noop(self, tmp_path: Path) -> None:
        _remove_manifest_files("kiro", [str(tmp_path / "gone.md")])


class TestRemoveClineSymlinks:
    def test_removes_symlinks(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        real = tmp_path / "real"
        real.mkdir()
        with patch("llm_prompts.install.Path.home", return_value=home):
            from llm_prompts.install import _get_cline_extra_dirs

            _, symlinks = _get_cline_extra_dirs()
            for dest in symlinks.values():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(real)

            _remove_cline_symlinks()

            for dest in symlinks.values():
                assert not dest.exists()
                assert not dest.is_symlink()

    def test_leaves_real_directory_untouched(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            from llm_prompts.install import _get_cline_extra_dirs

            _, symlinks = _get_cline_extra_dirs()
            rules_dest = symlinks["rules"]
            rules_dest.mkdir(parents=True)
            (rules_dest / "keep.md").write_text("mine", encoding="utf-8")

            _remove_cline_symlinks()

            assert rules_dest.is_dir()
            assert (rules_dest / "keep.md").exists()


class TestUnpatchKiroAgentConfig:
    def test_removes_only_kiro_resources(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            resources = _kiro_resources()
            config_path = tmp_path / "agent.json"
            config_path.write_text(
                json.dumps({"resources": [*resources, "file:///other.md"]}),
                encoding="utf-8",
            )

            _unpatch_kiro_agent_config(str(config_path))

            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["resources"] == ["file:///other.md"]

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        _unpatch_kiro_agent_config(str(tmp_path / "gone.json"))


class TestDisallowUpdateClaudeCode:
    def _write_settings(self, home: Path, allow: list[str]) -> Path:
        settings_path = home / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps({"permissions": {"allow": allow}}), encoding="utf-8"
        )
        return settings_path

    def test_removes_rule_keeps_others(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            settings_path = self._write_settings(
                home, ["Bash(llm-prompts update *)", "Bash(ls *)"]
            )

            _disallow_update_claude_code()

            data = json.loads(settings_path.read_text(encoding="utf-8"))
            assert data["permissions"]["allow"] == ["Bash(ls *)"]

    def test_missing_settings_is_noop(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            _disallow_update_claude_code()

    def test_rule_absent_is_noop(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            settings_path = self._write_settings(home, ["Bash(ls *)"])

            _disallow_update_claude_code()

            data = json.loads(settings_path.read_text(encoding="utf-8"))
            assert data["permissions"]["allow"] == ["Bash(ls *)"]


@pytest.fixture
def installed_home(tmp_path: Path):
    """Run `install claude-code` into a fake home with overlays/manifest redirected."""
    home = tmp_path / "home"
    home.mkdir()
    manifest = tmp_path / "installed.json"
    with (
        patch("llm_prompts.install.Path.home", return_value=home),
        patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
        patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
    ):
        install_main(["claude-code"])
        yield home


class TestUninstallEndToEnd:
    def test_uninstall_single_agent_removes_files_and_manifest(
        self, installed_home: Path, tmp_path: Path
    ) -> None:
        manifest = tmp_path / "installed.json"
        with (
            patch("llm_prompts.install.Path.home", return_value=installed_home),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
        ):
            entry = read_manifest()["claude-code"]
            assert entry["files"]
            assert all(Path(f).exists() for f in entry["files"])

            uninstall(["claude-code"])

            assert "claude-code" not in read_manifest()
            assert all(not Path(f).exists() for f in entry["files"])

    def test_uninstall_not_installed_warns_and_preserves_others(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
        ):
            write_manifest("kiro", [str(home / "keep.md")])

            uninstall(["codex"])

            assert "kiro" in read_manifest()

    def test_uninstall_all_removes_every_agent(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
        ):
            write_manifest("kiro", [])
            write_manifest("codex", [])

            uninstall(None)

            assert read_manifest() == {}
