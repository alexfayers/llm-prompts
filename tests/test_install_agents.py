"""Tests for the claude-code agents artifact type."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.install import (
    _apply_frontmatter_overrides,
    _claude_model_catalogue,
    _expand_agent_variants,
    _install_agents,
    _resolve_variant_model,
    get_managed_dirs,
)
from llm_prompts.install import main as install_main
from llm_prompts.render_template import parse_frontmatter


def _make_agent(directory: Path, name: str, body: str = "body") -> Path:
    """Create a markdown agent file under directory and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"---\nname: {name}\n---\n\n{body}\n", encoding="utf-8")
    return path


def _make_variant_template(
    directory: Path,
    name: str,
    stem: str,
    variants: str,
    *,
    description: str = "A generic agent.",
    body: str = "You are an agent.",
) -> Path:
    """Create a template source with a ``generate_variants`` frontmatter key."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        f"---\nname: {stem}\ndescription: {description}\n"
        f"disallowedTools: Agent\ngenerate_variants: {variants}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _isolated_model_catalogue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Resolve models against an empty home so tests never read the real settings."""
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    with patch("llm_prompts.install.Path.home", return_value=tmp_path / "empty-home"):
        yield


def _write_settings(home: Path, settings: dict[str, object]) -> None:
    """Write a Claude Code settings.json into a fake home directory."""
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


_BEDROCK_SETTINGS: dict[str, object] = {
    "modelOverrides": {
        "claude-haiku-4-5": "bedrock/claude-haiku-4-5-dated",
        "claude-opus-4-8[1m]": "bedrock/claude-opus-4-8[1m]",
        "claude-opus-5": "bedrock/claude-opus-5",
        "claude-opus-5[1m]": "bedrock/claude-opus-5[1m]",
        "claude-sonnet-4-6[1m]": "bedrock/claude-sonnet-4-6[1m]",
        "claude-sonnet-5": "bedrock/claude-sonnet-5",
    },
    "availableModels": ["claude-haiku-4-5", "claude-opus-5[1m]"],
}


class TestResolveVariantModel:
    def test_bedrock_alias_becomes_mapped_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        _write_settings(tmp_path, _BEDROCK_SETTINGS)

        with patch("llm_prompts.install.Path.home", return_value=tmp_path):
            catalogue = _claude_model_catalogue()

        assert _resolve_variant_model("haiku", catalogue) == (
            "bedrock/claude-haiku-4-5-dated"
        )

    def test_long_context_entry_preferred_for_same_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        _write_settings(tmp_path, _BEDROCK_SETTINGS)

        with patch("llm_prompts.install.Path.home", return_value=tmp_path):
            catalogue = _claude_model_catalogue()

        assert _resolve_variant_model("opus", catalogue) == "bedrock/claude-opus-5[1m]"

    def test_newest_version_wins_over_older_long_context_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        _write_settings(tmp_path, _BEDROCK_SETTINGS)

        with patch("llm_prompts.install.Path.home", return_value=tmp_path):
            catalogue = _claude_model_catalogue()

        assert _resolve_variant_model("sonnet", catalogue) == "bedrock/claude-sonnet-5"

    def test_non_bedrock_uses_available_models_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
        _write_settings(tmp_path, _BEDROCK_SETTINGS)

        with patch("llm_prompts.install.Path.home", return_value=tmp_path):
            catalogue = _claude_model_catalogue()

        assert _resolve_variant_model("opus", catalogue) == "claude-opus-5[1m]"
        assert _resolve_variant_model("haiku", catalogue) == "claude-haiku-4-5"

    def test_unmatched_family_keeps_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        _write_settings(tmp_path, _BEDROCK_SETTINGS)

        with patch("llm_prompts.install.Path.home", return_value=tmp_path):
            catalogue = _claude_model_catalogue()

        assert _resolve_variant_model("fable", catalogue) == "fable"

    def test_missing_settings_file_keeps_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")

        with patch("llm_prompts.install.Path.home", return_value=tmp_path):
            catalogue = _claude_model_catalogue()

        assert catalogue == {}
        assert _resolve_variant_model("haiku", catalogue) == "haiku"

    def test_unreadable_settings_keeps_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text(
            "{not json", encoding="utf-8"
        )

        with patch("llm_prompts.install.Path.home", return_value=tmp_path):
            catalogue = _claude_model_catalogue()

        assert catalogue == {}
        assert _resolve_variant_model("sonnet", catalogue) == "sonnet"

    def test_bedrock_without_model_overrides_keeps_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        _write_settings(tmp_path, {"availableModels": ["claude-haiku-4-5"]})

        with patch("llm_prompts.install.Path.home", return_value=tmp_path):
            catalogue = _claude_model_catalogue()

        assert _resolve_variant_model("haiku", catalogue) == "haiku"


class TestApplyFrontmatterOverrides:
    def test_replaces_existing_key(self) -> None:
        content = "---\ndisable-model-invocation: true\n---\n\nBody.\n"
        result = _apply_frontmatter_overrides(
            content, {"disable-model-invocation": "false"}
        )
        _, frontmatter = parse_frontmatter(result)
        assert frontmatter["disable-model-invocation"] == "false"

    def test_appends_absent_key(self) -> None:
        content = "---\nname: foo\n---\n\nBody.\n"
        result = _apply_frontmatter_overrides(content, {"priority": "1"})
        _, frontmatter = parse_frontmatter(result)
        assert frontmatter["name"] == "foo"
        assert frontmatter["priority"] == "1"

    def test_other_frontmatter_lines_byte_identical(self) -> None:
        content = '---\nname: foo\ndescription: "A thing"\n---\n\nBody.\n'
        result = _apply_frontmatter_overrides(content, {"name": "bar"})
        split = result.split("---\n")
        assert 'description: "A thing"' in split[1]

    def test_body_byte_identical(self) -> None:
        content = "---\nname: foo\n---\n\nLine one.\nLine two.\n"
        result = _apply_frontmatter_overrides(content, {"name": "bar"})
        body, _ = parse_frontmatter(result)
        assert body == "Line one.\nLine two.\n"

    def test_synthesizes_block_when_none_exists(self) -> None:
        content = "Body only, no frontmatter.\n"
        result = _apply_frontmatter_overrides(content, {"name": "foo"})
        body, frontmatter = parse_frontmatter(result)
        assert frontmatter["name"] == "foo"
        assert body == content


class TestExpandAgentVariants:
    def test_generates_one_file_per_token_with_model_and_effort(
        self, tmp_path: Path
    ) -> None:
        src = _make_variant_template(
            tmp_path, "worker.md", "worker", "sonnet-low,sonnet-medium"
        )

        generated = _expand_agent_variants(src)

        names = {name for name, _ in generated}
        assert names == {"worker-sonnet-low.md", "worker-sonnet-medium.md"}
        by_name = dict(generated)
        _, frontmatter = parse_frontmatter(by_name["worker-sonnet-low.md"])
        assert frontmatter["name"] == "worker-sonnet-low"
        assert frontmatter["model"] == "sonnet"
        assert frontmatter["effort"] == "low"

    def test_description_gets_model_effort_suffix(self, tmp_path: Path) -> None:
        src = _make_variant_template(
            tmp_path,
            "worker.md",
            "worker",
            "haiku-medium",
            description="Does mechanical things.",
        )

        generated = dict(_expand_agent_variants(src))

        _, frontmatter = parse_frontmatter(generated["worker-haiku-medium.md"])
        assert frontmatter["description"] == (
            "Does mechanical things. [haiku, medium effort]"
        )

    def test_body_and_other_frontmatter_carried_verbatim(self, tmp_path: Path) -> None:
        src = _make_variant_template(
            tmp_path, "worker.md", "worker", "sonnet-low", body="Line one.\nLine two."
        )

        generated = dict(_expand_agent_variants(src))

        body, frontmatter = parse_frontmatter(generated["worker-sonnet-low.md"])
        assert body.strip() == "Line one.\nLine two."
        assert frontmatter["disallowedTools"] == "Agent"

    def test_generate_variants_key_absent_from_output(self, tmp_path: Path) -> None:
        src = _make_variant_template(tmp_path, "worker.md", "worker", "sonnet-low")

        generated = dict(_expand_agent_variants(src))

        _, frontmatter = parse_frontmatter(generated["worker-sonnet-low.md"])
        assert "generate_variants" not in frontmatter

    def test_resolved_model_emitted_while_name_keeps_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        home = tmp_path / "home"
        _write_settings(home, _BEDROCK_SETTINGS)
        src = _make_variant_template(tmp_path, "worker.md", "worker", "haiku-low")

        with patch("llm_prompts.install.Path.home", return_value=home):
            generated = dict(_expand_agent_variants(src))

        _, frontmatter = parse_frontmatter(generated["worker-haiku-low.md"])
        assert frontmatter["model"] == "bedrock/claude-haiku-4-5-dated"
        assert frontmatter["name"] == "worker-haiku-low"
        assert frontmatter["description"].endswith("[haiku, low effort]")

    def test_malformed_token_is_skipped(self, tmp_path: Path) -> None:
        src = _make_variant_template(
            tmp_path, "worker.md", "worker", "sonnet-low,bogus,haiku-high"
        )

        generated = dict(_expand_agent_variants(src))

        assert set(generated) == {"worker-sonnet-low.md", "worker-haiku-high.md"}


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

    def test_variant_template_writes_generated_files_alongside_symlinks(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "agents"
        _make_agent(src, "architect.md", "arch")
        _make_variant_template(src, "worker.md", "worker", "sonnet-low,haiku-high")
        dest = tmp_path / "dest"

        managed = _install_agents([src], dest)

        assert managed == {
            "architect.md",
            "worker-sonnet-low.md",
            "worker-haiku-high.md",
        }
        assert (dest / "architect.md").is_symlink()
        assert not (dest / "worker-sonnet-low.md").is_symlink()
        assert (dest / "worker-sonnet-low.md").is_file()
        assert not (dest / "worker.md").exists()

    def test_variant_template_second_run_does_not_rewrite(self, tmp_path: Path) -> None:
        src = tmp_path / "agents"
        _make_variant_template(src, "worker.md", "worker", "sonnet-low")
        dest = tmp_path / "dest"

        _install_agents([src], dest)
        generated = dest / "worker-sonnet-low.md"
        before = generated.stat().st_mtime_ns

        second = _install_agents([src], dest)

        assert second == {"worker-sonnet-low.md"}
        assert generated.stat().st_mtime_ns == before

    def test_overlay_variant_template_overrides_base(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        _make_variant_template(
            base_dir, "worker.md", "worker", "sonnet-low", description="BASE"
        )
        overlay_dir = tmp_path / "overlay"
        _make_variant_template(
            overlay_dir, "worker.md", "worker", "haiku-high", description="OVL"
        )
        dest = tmp_path / "dest"

        managed = _install_agents([overlay_dir, base_dir], dest)

        assert managed == {"worker-haiku-high.md"}
        assert not (dest / "worker-sonnet-low.md").exists()
        content = (dest / "worker-haiku-high.md").read_text(encoding="utf-8")
        assert "OVL" in content


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
    def test_worker_reasoner_architect_and_surveyor_variants_installed_as_generated_files(
        self, claude_home: Path
    ) -> None:
        agents_dir = claude_home / ".claude" / "agents"

        expected = {
            "worker-sonnet-low.md",
            "worker-sonnet-medium.md",
            "worker-sonnet-high.md",
            "worker-haiku-low.md",
            "worker-haiku-medium.md",
            "worker-haiku-high.md",
            "reasoner-opus-medium.md",
            "reasoner-opus-high.md",
            "reasoner-opus-xhigh.md",
            "architect-opus-medium.md",
            "architect-opus-high.md",
            "architect-opus-xhigh.md",
            "surveyor-sonnet-low.md",
            "surveyor-sonnet-medium.md",
            "surveyor-sonnet-high.md",
        }
        for name in expected:
            path = agents_dir / name
            assert path.is_file()
            assert not path.is_symlink()

        assert not (agents_dir / "worker.md").exists()
        assert not (agents_dir / "reasoner.md").exists()
        assert not (agents_dir / "architect.md").exists()
        assert not (agents_dir / "surveyor.md").exists()

        _, frontmatter = parse_frontmatter(
            (agents_dir / "worker-sonnet-low.md").read_text(encoding="utf-8")
        )
        assert frontmatter["model"] == "sonnet"
        assert frontmatter["effort"] == "low"
        assert "generate_variants" not in frontmatter

    def test_surveyor_variant_keeps_read_only_tool_restriction(
        self, claude_home: Path
    ) -> None:
        agents_dir = claude_home / ".claude" / "agents"

        _, frontmatter = parse_frontmatter(
            (agents_dir / "surveyor-sonnet-medium.md").read_text(encoding="utf-8")
        )
        disallowed = frontmatter["disallowedTools"]
        assert "Write" in disallowed
        assert "Edit" in disallowed
        assert "NotebookEdit" in disallowed


class TestClaudeCodeAgentsManifestTracking:
    def test_generated_variants_tracked_and_removed_on_uninstall(
        self, claude_home: Path
    ) -> None:
        from llm_prompts.install import uninstall
        from llm_prompts.manifest import read_manifest

        agents_dir = claude_home / ".claude" / "agents"
        manifest_files = set(read_manifest()["claude-code"]["files"])
        assert str(agents_dir / "worker-sonnet-low.md") in manifest_files
        assert str(agents_dir / "reasoner-opus-high.md") in manifest_files

        uninstall(["claude-code"])

        assert not (agents_dir / "worker-sonnet-low.md").exists()
        assert not (agents_dir / "reasoner-opus-high.md").exists()
        assert "claude-code" not in read_manifest()


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
