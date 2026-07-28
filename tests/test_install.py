"""Tests for env-gated rule installation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from llm_prompts.install import (
    _Agent,
    _collect_content_srcs,
    _env_var_set,
    _excluded_targets,
    _GATING_FRONTMATTER_KEYS,
    _install_linked,
    _install_skills,
    _passes_requires_gate,
)
from llm_prompts.render_template import render_template, strip_gating_keys


def _make_rule(directory: Path, name: str, body: str = "body") -> Path:
    """Create a markdown rule file under directory and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


class TestEnvVarSet:
    def test_true_when_set_in_os_environ(self) -> None:
        with patch.dict("os.environ", {"MY_FLAG": "1"}):
            assert _env_var_set("MY_FLAG") is True

    def test_false_when_unset_and_no_settings_file(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("llm_prompts.install.Path.home", return_value=tmp_path),
        ):
            assert _env_var_set("MY_FLAG") is False

    def test_true_when_set_in_claude_settings_env_block(self, tmp_path: Path) -> None:
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(
            '{"env": {"MY_FLAG": "1"}}', encoding="utf-8"
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("llm_prompts.install.Path.home", return_value=tmp_path),
        ):
            assert _env_var_set("MY_FLAG") is True

    def test_false_when_settings_json_is_malformed(self, tmp_path: Path) -> None:
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text("not json", encoding="utf-8")
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("llm_prompts.install.Path.home", return_value=tmp_path),
        ):
            assert _env_var_set("MY_FLAG") is False


class TestPassesRequiresGate:
    def test_true_when_no_frontmatter(self, tmp_path: Path) -> None:
        rule = _make_rule(tmp_path, "rule.md", "# Rule\n\nbody\n")
        assert _passes_requires_gate(rule) is True

    def test_true_when_required_env_is_set(self, tmp_path: Path) -> None:
        rule = _make_rule(
            tmp_path,
            "rule.md",
            "---\nrequires_env: MY_FLAG\n---\n\n# Rule\n",
        )
        with patch.dict("os.environ", {"MY_FLAG": "1"}):
            assert _passes_requires_gate(rule) is True

    def test_false_when_required_env_is_unset(self, tmp_path: Path) -> None:
        rule = _make_rule(
            tmp_path,
            "rule.md",
            "---\nrequires_env: MY_FLAG\n---\n\n# Rule\n",
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("llm_prompts.install.Path.home", return_value=tmp_path),
        ):
            assert _passes_requires_gate(rule) is False

    def test_true_when_required_command_present(self, tmp_path: Path) -> None:
        rule = _make_rule(
            tmp_path,
            "rule.md",
            "---\nrequires_command: mytool\n---\n\n# Rule\n",
        )
        with patch("llm_prompts.install.shutil.which", return_value="/usr/bin/mytool"):
            assert _passes_requires_gate(rule) is True

    def test_false_when_required_command_absent(self, tmp_path: Path) -> None:
        rule = _make_rule(
            tmp_path,
            "rule.md",
            "---\nrequires_command: mytool\n---\n\n# Rule\n",
        )
        with patch("llm_prompts.install.shutil.which", return_value=None):
            assert _passes_requires_gate(rule) is False

    def test_both_gates_present_requires_both(self, tmp_path: Path) -> None:
        rule = _make_rule(
            tmp_path,
            "rule.md",
            "---\nrequires_env: MY_FLAG\nrequires_command: mytool\n---\n\n# Rule\n",
        )
        with (
            patch.dict("os.environ", {"MY_FLAG": "1"}),
            patch("llm_prompts.install.shutil.which", return_value="/usr/bin/mytool"),
        ):
            assert _passes_requires_gate(rule) is True
        with (
            patch.dict("os.environ", {"MY_FLAG": "1"}),
            patch("llm_prompts.install.shutil.which", return_value=None),
        ):
            assert _passes_requires_gate(rule) is False


class TestCollectContentSrcsEnvGate:
    def test_gated_file_excluded_when_env_unset(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        _make_rule(shared, "coding.md", "# coding\n")
        _make_rule(
            shared,
            "agent-teams.md",
            "---\nrequires_env: MY_FLAG\n---\n\n# Agent teams\n",
        )
        agent = _Agent(
            name="claude-code",
            root_dir=root,
            dirs={"claude-code": {"rules": tmp_path / "dest"}},
        )

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("llm_prompts.install.Path.home", return_value=tmp_path / "home"),
        ):
            collected = _collect_content_srcs(
                agent=agent,
                subdir="rules",
                shared_src=shared,
                overlay_srcs=[],
                overlay_agent_srcs=[],
            )

        names = [name for name, _, _ in collected]
        assert names == ["coding.md"]

    def test_gated_file_included_when_env_set(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        _make_rule(shared, "coding.md", "# coding\n")
        _make_rule(
            shared,
            "agent-teams.md",
            "---\nrequires_env: MY_FLAG\n---\n\n# Agent teams\n",
        )
        agent = _Agent(
            name="claude-code",
            root_dir=root,
            dirs={"claude-code": {"rules": tmp_path / "dest"}},
        )

        with patch.dict("os.environ", {"MY_FLAG": "1"}):
            collected = _collect_content_srcs(
                agent=agent,
                subdir="rules",
                shared_src=shared,
                overlay_srcs=[],
                overlay_agent_srcs=[],
            )

        names = [name for name, _, _ in collected]
        assert names == ["agent-teams.md", "coding.md"]


class TestExcludedTargets:
    def test_empty_when_key_absent(self, tmp_path: Path) -> None:
        rule = _make_rule(tmp_path, "rule.md", "---\nname: x\n---\n\n# Rule\n")
        assert _excluded_targets(rule) == set()

    def test_single_value(self, tmp_path: Path) -> None:
        rule = _make_rule(tmp_path, "rule.md", "---\nexclude_targets: codex\n---\n")
        assert _excluded_targets(rule) == {"codex"}

    def test_comma_separated_strips_whitespace(self, tmp_path: Path) -> None:
        rule = _make_rule(
            tmp_path, "rule.md", "---\nexclude_targets: codex, cline\n---\n"
        )
        assert _excluded_targets(rule) == {"codex", "cline"}


class TestInstallSkillsGating:
    def _make_skill(self, skills_src: Path, name: str, skill_md: str) -> None:
        skill_dir = skills_src / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    def test_requires_command_unsatisfied_skill_not_symlinked(
        self, tmp_path: Path
    ) -> None:
        skills_src = tmp_path / "skills_src"
        self._make_skill(skills_src, "plain", "# Plain\n")
        self._make_skill(skills_src, "gated", "---\nrequires_command: sometool\n---\n")
        agents_dir = tmp_path / "agents"

        with patch("llm_prompts.install.shutil.which", return_value=None):
            managed = _install_skills([skills_src], agents_dir, "claude-code")

        assert (agents_dir / "skills" / "plain").is_symlink() is True
        assert (agents_dir / "skills" / "gated").exists() is False
        assert "plain" in managed
        assert "gated" not in managed

    def test_exclude_targets_skips_named_agent_only(self, tmp_path: Path) -> None:
        skills_src = tmp_path / "skills_src"
        self._make_skill(
            skills_src,
            "ask-codex",
            "---\nrequires_command: sometool\nexclude_targets: codex\n---\n",
        )

        codex_agents = tmp_path / "codex_agents"
        with patch(
            "llm_prompts.install.shutil.which", return_value="/usr/bin/sometool"
        ):
            codex_managed = _install_skills([skills_src], codex_agents, "codex")

        assert (codex_agents / "skills" / "ask-codex").exists() is False
        assert "ask-codex" not in codex_managed

        cc_agents = tmp_path / "cc_agents"
        with patch(
            "llm_prompts.install.shutil.which", return_value="/usr/bin/sometool"
        ):
            cc_managed = _install_skills([skills_src], cc_agents, "claude-code")

        assert (cc_agents / "skills" / "ask-codex").is_symlink() is True
        assert "ask-codex" in cc_managed

    def test_overlay_skill_overrides_base_on_name_collision(
        self, tmp_path: Path
    ) -> None:
        base_dir = tmp_path / "base"
        self._make_skill(base_dir, "shared-only", "# Shared\nBASE\n")
        self._make_skill(base_dir, "collide", "# Collide\nBASE-COLLIDE\n")
        overlay_dir = tmp_path / "overlay"
        self._make_skill(overlay_dir, "collide", "# Collide\nOVERLAY-COLLIDE\n")
        self._make_skill(overlay_dir, "overlay-only", "# Overlay\nOVL\n")
        agents_dir = tmp_path / "agents"

        managed = _install_skills([overlay_dir, base_dir], agents_dir, "claude-code")

        collide = agents_dir / "skills" / "collide"
        assert collide.is_symlink()
        assert "OVERLAY-COLLIDE" in (collide / "SKILL.md").read_text(encoding="utf-8")
        assert managed == {"shared-only", "collide", "overlay-only"}


_NON_GATING_FRONTMATTER = (
    "---\n"
    "description: Automate a new task\n"
    "author: someone\n"
    "version: 1.0.0\n"
    'category: "Cline Core"\n'
    "tags: automation, task\n"
    "globs: **/*.md\n"
    "---\n"
    "\n"
    "# Body\n"
)


class TestStripGatingKeys:
    def test_only_gating_keys_removes_block(self) -> None:
        content = "---\nrequires_env: MY_FLAG\n---\n\n# Body\n"
        assert strip_gating_keys(content, _GATING_FRONTMATTER_KEYS) == "\n# Body\n"

    def test_only_non_gating_keys_unchanged(self) -> None:
        assert (
            strip_gating_keys(_NON_GATING_FRONTMATTER, _GATING_FRONTMATTER_KEYS)
            == _NON_GATING_FRONTMATTER
        )

    def test_mixed_keys_keeps_only_non_gating(self) -> None:
        content = (
            "---\n"
            "requires_env: MY_FLAG\n"
            "description: A thing\n"
            "requires_command: sometool\n"
            'category: "Cline Core"\n'
            "exclude_targets: codex\n"
            "---\n"
            "\n"
            "# Body\n"
        )
        expected = '---\ndescription: A thing\ncategory: "Cline Core"\n---\n\n# Body\n'
        assert strip_gating_keys(content, _GATING_FRONTMATTER_KEYS) == expected

    def test_no_frontmatter_unchanged(self) -> None:
        content = "# Body\n\nsome text\n"
        assert strip_gating_keys(content, _GATING_FRONTMATTER_KEYS) == content

    def test_idempotent(self) -> None:
        content = "---\nrequires_env: MY_FLAG\ndescription: A thing\n---\n\n# Body\n"
        once = strip_gating_keys(content, _GATING_FRONTMATTER_KEYS)
        twice = strip_gating_keys(once, _GATING_FRONTMATTER_KEYS)
        assert once == twice


class TestInstallLinked:
    def test_only_gating_keys_stripped_from_dest(self, tmp_path: Path) -> None:
        src = _make_rule(
            tmp_path / "src", "rule.md", "---\nrequires_env: MY_FLAG\n---\n\n# Body\n"
        )
        dest = tmp_path / "dest" / "rule.md"
        _install_linked(src, dest, "rule")
        installed = dest.read_text(encoding="utf-8")
        assert not installed.startswith("---")
        assert "# Body" in installed

    def test_non_gating_frontmatter_preserved_verbatim(self, tmp_path: Path) -> None:
        src = _make_rule(tmp_path / "src", "wf.md", _NON_GATING_FRONTMATTER)
        dest = tmp_path / "dest" / "wf.md"
        _install_linked(src, dest, "wf")
        assert dest.read_text(encoding="utf-8") == _NON_GATING_FRONTMATTER

    def test_mixed_frontmatter_keeps_only_non_gating(self, tmp_path: Path) -> None:
        body = (
            "---\n"
            "requires_env: MY_FLAG\n"
            "description: A thing\n"
            'category: "Cline Core"\n'
            "---\n"
            "\n"
            "# Body\n"
        )
        src = _make_rule(tmp_path / "src", "rule.md", body)
        dest = tmp_path / "dest" / "rule.md"
        _install_linked(src, dest, "rule")
        installed = dest.read_text(encoding="utf-8")
        assert "requires_env" not in installed
        assert "description: A thing" in installed
        assert 'category: "Cline Core"' in installed

    def test_no_frontmatter_unchanged(self, tmp_path: Path) -> None:
        body = "# Body\n\nsome text\n"
        src = _make_rule(tmp_path / "src", "rule.md", body)
        dest = tmp_path / "dest" / "rule.md"
        _install_linked(src, dest, "rule")
        assert dest.read_text(encoding="utf-8") == body


class TestRenderForKiro:
    def _render(self, tmp_path: Path, template_body: str) -> str:
        template = tmp_path / "rule.md"
        template.write_text(template_body, encoding="utf-8")
        vars_file = tmp_path / "vars.json"
        vars_file.write_text("{}", encoding="utf-8")
        return render_template(str(template), str(vars_file), "kiro")

    def test_no_frontmatter_body_only(self, tmp_path: Path) -> None:
        output = self._render(tmp_path, "# Rule\n\nbody\n")
        assert "---" not in output
        assert "inclusion:" not in output
        assert output.endswith("\n")

    def test_always_inclusion(self, tmp_path: Path) -> None:
        output = self._render(tmp_path, "---\nkiro_inclusion: always\n---\n\n# Rule\n")
        assert output.startswith("---\ninclusion: always\n---")
        assert output.endswith("\n")

    def test_manual_inclusion_omits_extras(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path,
            "---\nkiro_inclusion: manual\ndescription: some text\n---\n\n# Rule\n",
        )
        assert "inclusion: manual" in output
        assert "name:" not in output
        assert "description:" not in output
        assert "fileMatchPattern:" not in output
        assert output.endswith("\n")

    def test_filematch_single_pattern(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path,
            "---\nkiro_inclusion: fileMatch\n"
            "kiro_file_match_pattern: '**/*.py'\n---\n\n# Rule\n",
        )
        assert "inclusion: fileMatch" in output
        assert "fileMatchPattern: '**/*.py'" in output
        assert "[" not in output
        assert output.endswith("\n")

    def test_filematch_multi_pattern(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path,
            "---\nkiro_inclusion: fileMatch\n"
            "kiro_file_match_pattern: '**/*.py, **/*.pyi'\n---\n\n# Rule\n",
        )
        assert "inclusion: fileMatch" in output
        assert "fileMatchPattern: ['**/*.py', '**/*.pyi']" in output
        assert output.endswith("\n")

    def test_auto_inclusion_with_name_and_description(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path,
            "---\nkiro_inclusion: auto\nname: subagents\n"
            "description: some text\n---\n\n# Rule\n",
        )
        assert "inclusion: auto" in output
        assert "name: subagents" in output
        assert "description: some text" in output
        assert output.endswith("\n")

    def test_copilot_only_frontmatter_ignored(self, tmp_path: Path) -> None:
        output = self._render(tmp_path, "---\ncopilot_apply_to: '**'\n---\n\n# Rule\n")
        assert "---" not in output
        assert "inclusion:" not in output
        assert "applyTo" not in output
        assert output.endswith("\n")
