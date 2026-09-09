"""Tests for the antigravity install target."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.install import get_managed_dirs
from llm_prompts.install import main as install_main
from llm_prompts.render_template import render_template


def _make_rule(directory: Path, name: str, body: str = "body") -> Path:
    """Create a markdown rule file under directory and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    return path


class TestRenderForAntigravity:
    def test_strips_frontmatter_and_normalises_body(self, tmp_path: Path) -> None:
        template = tmp_path / "rule.md"
        template.write_text(
            "---\ndescription: A rule\ncopilot_apply_to: '**'\n---\n\n"
            "# Heading\n\n\n\nBody text.\n",
            encoding="utf-8",
        )
        vars_file = tmp_path / "vars.json"
        vars_file.write_text("{}", encoding="utf-8")

        output = render_template(str(template), str(vars_file), "antigravity")

        assert "description:" not in output
        assert "---" not in output
        assert "# Heading" in output
        assert "\n\n\n" not in output
        assert output.endswith("\n")


@pytest.fixture
def antigravity_home(tmp_path: Path) -> Iterator[Path]:
    """Run `install antigravity` into a fake home with overlays and manifest redirected."""
    home = tmp_path / "home"
    home.mkdir()
    manifest = tmp_path / "installed.json"
    with (
        patch("llm_prompts.install.Path.home", return_value=home),
        patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
        patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
    ):
        install_main(["antigravity"])
        yield home


class TestAntigravityInstallLayout:
    def test_rules_land_in_single_agents_md(self, antigravity_home: Path) -> None:
        agents_md = antigravity_home / ".gemini" / "config" / "AGENTS.md"
        assert agents_md.is_file()
        assert not (antigravity_home / ".gemini" / "config" / "rules").exists()

    def test_workflows_land_as_workflow_files(self, antigravity_home: Path) -> None:
        workflows = antigravity_home / ".gemini" / "config" / "workflows"
        assert (workflows / "simplify.md").is_file()
        assert (workflows / "word-god.md").is_file()

    def test_skills_materialize_into_antigravity_skills(
        self, antigravity_home: Path
    ) -> None:
        skills = antigravity_home / ".gemini" / "config" / "skills"
        assert (skills / "tdd").is_dir() and not (skills / "tdd").is_symlink()
        assert (skills / "git-usage").is_dir() and not (
            skills / "git-usage"
        ).is_symlink()

    def test_reinstall_removes_stale_workflow(
        self, antigravity_home: Path, tmp_path: Path
    ) -> None:
        stray = antigravity_home / ".gemini" / "config" / "workflows" / "stray.md"
        stray.write_text("stale", encoding="utf-8")
        manifest = tmp_path / "installed.json"
        import json

        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["agents"]["antigravity"]["files"].append(str(stray))
        manifest.write_text(json.dumps(data), encoding="utf-8")

        with (
            patch("llm_prompts.install.Path.home", return_value=antigravity_home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
        ):
            install_main(["antigravity"])

        assert not stray.exists()


class TestAntigravityManagedDirs:
    def test_includes_workflows_and_skills_not_bare_gemini_config(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            managed = set(get_managed_dirs())

        assert home / ".gemini" / "config" / "workflows" in managed
        assert home / ".gemini" / "config" / "skills" in managed
        assert home / ".gemini" / "config" not in managed
