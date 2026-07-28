"""Tests for the claude-code agents artifact type."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.install import _install_agents, get_managed_dirs
from llm_prompts.install import main as install_main


def _make_agent(directory: Path, name: str, body: str = "body") -> Path:
    """Create a markdown agent file under directory and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"---\nname: {name}\n---\n\n{body}\n", encoding="utf-8")
    return path


class TestInstallAgents:
    def test_symlinks_source_files_into_dest(self, tmp_path: Path) -> None:
        src = tmp_path / "agents"
        dest = tmp_path / "dest"
        a = _make_agent(src, "architect.md", "arch")
        b = _make_agent(src, "reviewer.md", "review")

        managed = _install_agents([src], dest)

        assert (dest / "architect.md").is_symlink()
        assert (dest / "reviewer.md").is_symlink()
        assert (dest / "architect.md").resolve() == a.resolve()
        assert (dest / "reviewer.md").resolve() == b.resolve()
        assert managed == {"architect.md", "reviewer.md"}

    def test_idempotent_second_run_keeps_valid_symlink(self, tmp_path: Path) -> None:
        src = tmp_path / "agents"
        dest = tmp_path / "dest"
        a = _make_agent(src, "architect.md", "arch")

        _install_agents([src], dest)
        second = _install_agents([src], dest)

        assert (dest / "architect.md").is_symlink()
        assert (dest / "architect.md").resolve() == a.resolve()
        assert second == {"architect.md"}

    def test_replaces_preexisting_regular_file_with_symlink(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "agents"
        dest = tmp_path / "dest"
        a = _make_agent(src, "architect.md", "source content")
        dest.mkdir()
        (dest / "architect.md").write_text("hand-placed", encoding="utf-8")

        managed = _install_agents([src], dest)

        assert (dest / "architect.md").is_symlink()
        assert (dest / "architect.md").read_text(encoding="utf-8") == a.read_text(
            encoding="utf-8"
        )
        assert managed == {"architect.md"}

    def test_missing_source_dir_is_noop(self, tmp_path: Path) -> None:
        managed = _install_agents([tmp_path / "nope"], tmp_path / "dest")

        assert managed == set()
        assert not (tmp_path / "dest").exists()

    def test_overlay_agent_overrides_base_on_name_collision(
        self, tmp_path: Path
    ) -> None:
        base_dir = tmp_path / "base"
        _make_agent(base_dir, "base-only.md", "BASE")
        _make_agent(base_dir, "collide.md", "BASE-C")
        overlay_dir = tmp_path / "overlay"
        _make_agent(overlay_dir, "collide.md", "OVL-C")
        _make_agent(overlay_dir, "overlay-only.md", "OVL")
        dest = tmp_path / "dest"

        managed = _install_agents([overlay_dir, base_dir], dest)

        collide = dest / "collide.md"
        assert collide.is_symlink()
        assert "OVL-C" in collide.read_text(encoding="utf-8")
        assert managed == {"base-only.md", "collide.md", "overlay-only.md"}


@pytest.fixture
def claude_home(tmp_path: Path):
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


class TestClaudeCodeAgentsInstallLayout:
    def test_architect_installs_as_symlink_to_source(self, claude_home: Path) -> None:
        from importlib.resources import files

        architect = claude_home / ".claude" / "agents" / "architect.md"
        source = (
            Path(str(files("llm_prompts") / "prompts"))
            / "claude-code"
            / "agents"
            / "architect.md"
        )

        assert architect.is_symlink()
        assert architect.resolve() == source.resolve()
        assert architect.read_text(encoding="utf-8") == source.read_text(
            encoding="utf-8"
        )


class TestClaudeCodeManagedDirs:
    def test_includes_agents_dir(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            managed = set(get_managed_dirs())

        assert home / ".claude" / "agents" in managed


class TestCollectSources:
    def test_claude_code_includes_architect_agent(self) -> None:
        from llm_prompts.cli import _collect_sources

        sources = _collect_sources("claude-code")

        assert "agents/architect.md" in sources

    def test_non_claude_code_agent_has_no_agents_key(self) -> None:
        from llm_prompts.cli import _collect_sources

        sources = _collect_sources("kiro")

        assert not any(key.startswith("agents/") for key in sources)
