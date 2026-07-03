"""Tests for the codex install target."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.install import (
    _Agent,
    _CodexAgent,
    _collect_content_srcs,
    _ensure_codex_doc_limit,
    get_managed_dirs,
)
from llm_prompts.install import main as install_main
from llm_prompts.render_template import render_template


def _make_rule(directory: Path, name: str, body: str = "body") -> Path:
    """Create a markdown rule file under directory and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    return path


class TestRenderForCodex:
    def test_strips_frontmatter_and_normalises_body(self, tmp_path: Path) -> None:
        template = tmp_path / "rule.md"
        template.write_text(
            "---\ndescription: A rule\ncopilot_apply_to: '**'\n---\n\n"
            "# Heading\n\n\n\nBody text.\n",
            encoding="utf-8",
        )
        vars_file = tmp_path / "vars.json"
        vars_file.write_text("{}", encoding="utf-8")

        output = render_template(str(template), str(vars_file), "codex")

        assert "description:" not in output
        assert "---" not in output
        assert "# Heading" in output
        assert "\n\n\n" not in output
        assert output.endswith("\n")


class TestCollectContentSrcs:
    def test_overlay_wins_over_shared_and_orders_overlay_first(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        overlay = tmp_path / "overlay" / "shared" / "rules"
        _make_rule(shared, "coding.md", "shared-coding")
        _make_rule(shared, "git.md", "shared-git")
        _make_rule(overlay, "coding.md", "overlay-coding")

        agent = _Agent(
            name="codex", root_dir=root, dirs={"codex": {"rules": tmp_path / "dest"}}
        )
        collected = _collect_content_srcs(
            agent=agent,
            subdir="rules",
            shared_src=shared,
            overlay_srcs=[overlay],
            overlay_agent_srcs=[],
        )

        names = [name for name, _, _ in collected]
        sources = {name: src for name, src, _ in collected}
        assert names == ["coding.md", "git.md"]
        assert sources["coding.md"].read_text(encoding="utf-8").endswith(
            "overlay-coding\n"
        )

    def test_includes_agent_specific_when_not_in_shared(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        agent_rules = root / "codex" / "rules"
        _make_rule(shared, "coding.md", "shared-coding")
        _make_rule(agent_rules, "planning.md", "agent-planning")

        agent = _Agent(
            name="codex", root_dir=root, dirs={"codex": {"rules": tmp_path / "dest"}}
        )
        collected = _collect_content_srcs(
            agent=agent,
            subdir="rules",
            shared_src=shared,
            overlay_srcs=[],
            overlay_agent_srcs=[],
        )

        names = [name for name, _, _ in collected]
        agent_specific = {name: flag for name, _, flag in collected}
        assert names == ["coding.md", "planning.md"]
        assert agent_specific["coding.md"] is False
        assert agent_specific["planning.md"] is True


class TestCodexAgentsMdConcat:
    def _build(self, tmp_path: Path) -> _CodexAgent:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        _make_rule(shared, "000-canary.md", "canary body")
        _make_rule(shared, "coding.md", "coding body")
        _make_rule(root / "codex" / "rules", "planning.md", "planning body")
        (root / "codex" / "vars.json").write_text("{}", encoding="utf-8")
        dirs = {"codex": {"rules": tmp_path / "home" / ".codex"}}
        return _CodexAgent(name="codex", root_dir=root, dirs=dirs)

    def test_writes_single_agents_md_file(self, tmp_path: Path) -> None:
        agent = self._build(tmp_path)
        shared = agent.root_dir / "shared" / "rules"

        installed = agent.install_rules(
            shared_src=shared, overlay_srcs=[], overlay_agent_srcs=[]
        )

        agents_md = tmp_path / "home" / ".codex" / "AGENTS.md"
        assert installed == {"AGENTS.md"}
        assert agents_md.is_file()
        assert not (tmp_path / "home" / ".codex" / "coding.md").exists()

    def test_concatenates_in_filename_order_deduped_bodies_only(
        self, tmp_path: Path
    ) -> None:
        agent = self._build(tmp_path)
        shared = agent.root_dir / "shared" / "rules"

        agent.install_rules(shared_src=shared, overlay_srcs=[], overlay_agent_srcs=[])

        content = (tmp_path / "home" / ".codex" / "AGENTS.md").read_text(
            encoding="utf-8"
        )
        assert "---" not in content
        assert content.index("canary body") < content.index("coding body")
        assert content.index("coding body") < content.index("planning body")
        assert content.endswith("\n")
        assert "\n\n\n" not in content


@pytest.fixture
def codex_home(tmp_path: Path):
    """Run `install codex` into a fake home with overlays and manifest redirected."""
    home = tmp_path / "home"
    home.mkdir()
    manifest = tmp_path / "installed.json"
    with (
        patch("llm_prompts.install.Path.home", return_value=home),
        patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
        patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
    ):
        install_main(["codex"])
        yield home


class TestCodexInstallLayout:
    def test_rules_land_in_single_agents_md(self, codex_home: Path) -> None:
        agents_md = codex_home / ".codex" / "AGENTS.md"
        assert agents_md.is_file()
        assert not (codex_home / ".codex" / "rules").exists()

    def test_workflows_land_as_prompt_files(self, codex_home: Path) -> None:
        prompts = codex_home / ".codex" / "prompts"
        assert (prompts / "simplify.md").is_file()
        assert (prompts / "word-god.md").is_file()

    def test_skills_symlink_into_codex_skills(self, codex_home: Path) -> None:
        skills = codex_home / ".codex" / "skills"
        assert (skills / "tdd").is_symlink()
        assert (skills / "git-usage").is_symlink()

    def test_reinstall_removes_stale_prompt(self, codex_home: Path, tmp_path: Path):
        stray = codex_home / ".codex" / "prompts" / "stray.md"
        stray.write_text("stale", encoding="utf-8")
        manifest = tmp_path / "installed.json"
        import json

        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["agents"]["codex"]["files"].append(str(stray))
        manifest.write_text(json.dumps(data), encoding="utf-8")

        with (
            patch("llm_prompts.install.Path.home", return_value=codex_home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
        ):
            install_main(["codex"])

        assert not stray.exists()


class TestCodexManagedDirs:
    def test_includes_prompts_and_skills_not_bare_codex_home(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            managed = set(get_managed_dirs())

        assert home / ".codex" / "prompts" in managed
        assert home / ".codex" / "skills" in managed
        assert home / ".codex" not in managed


class TestCodexDocLimit:
    def _write(self, tmp_path: Path, config: str, agents_md_bytes: int):
        config_path = tmp_path / "config.toml"
        config_path.write_text(config, encoding="utf-8")
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("x" * agents_md_bytes, encoding="utf-8")
        return config_path, agents_md

    def test_inserts_limit_before_first_table_when_over(self, tmp_path: Path) -> None:
        config = 'model = "gpt-5"\n\n[mcp_servers.foo]\ncommand = "foo"\n'
        config_path, agents_md = self._write(tmp_path, config, 40000)

        _ensure_codex_doc_limit(config_path, agents_md)

        text = config_path.read_text(encoding="utf-8")
        assert "project_doc_max_bytes = 65536" in text
        assert text.index("project_doc_max_bytes") < text.index("[mcp_servers.foo]")
        assert 'model = "gpt-5"' in text
        assert 'command = "foo"' in text

    def test_no_change_when_key_present(self, tmp_path: Path) -> None:
        config = "project_doc_max_bytes = 40000\n\n[t]\nx = 1\n"
        config_path, agents_md = self._write(tmp_path, config, 40000)

        _ensure_codex_doc_limit(config_path, agents_md)

        assert config_path.read_text(encoding="utf-8") == config

    def test_no_change_when_under_limit(self, tmp_path: Path) -> None:
        config = 'model = "gpt-5"\n\n[t]\nx = 1\n'
        config_path, agents_md = self._write(tmp_path, config, 100)

        _ensure_codex_doc_limit(config_path, agents_md)

        assert config_path.read_text(encoding="utf-8") == config

    def test_install_raises_limit_for_real_agents_md(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        codex_dir = home / ".codex"
        codex_dir.mkdir(parents=True)
        (codex_dir / "config.toml").write_text(
            'model = "gpt-5"\n\n[mcp_servers.foo]\ncommand = "foo"\n',
            encoding="utf-8",
        )
        manifest = tmp_path / "installed.json"
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
        ):
            install_main(["codex"])

        assert (codex_dir / "AGENTS.md").stat().st_size > 0
        config_text = (codex_dir / "config.toml").read_text(encoding="utf-8")
        agents_md_size = (codex_dir / "AGENTS.md").stat().st_size
        expected = agents_md_size > 32768
        assert ("project_doc_max_bytes = 65536" in config_text) is expected
