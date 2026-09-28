"""Tests for env-gated rule installation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from conftest import run_capturing_exit

from llm_prompts.install import (
    _GATING_FRONTMATTER_KEYS,
    _Agent,
    _carry_forward,
    _cleanup_stale,
    _collect_content_srcs,
    _env_var_set,
    _excluded_targets,
    _get_cline_extra_dirs,
    _get_dirs,
    _install_agents,
    _install_content,
    _install_linked,
    _install_plugin_skills,
    _install_rendered,
    _install_skills,
    _linked_content,
    _materialize_builtin_skill,
    _materialize_override_skill,
    _passes_requires_gate,
    _rendered_content,
    get_source_for_managed_file,
)
from llm_prompts.install import main as install_main
from llm_prompts.manifest import AgentManifest
from llm_prompts.render_template import (
    render_template,
    resolve_frontmatter,
    split_frontmatter,
    strip_gating_keys,
)
from llm_prompts.size_guard import Violation
from llm_prompts.size_limits import AGENT_DESCRIPTION_CHARS, FINALS


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

    def test_requires_command_unsatisfied_skill_not_materialized(
        self, tmp_path: Path
    ) -> None:
        skills_src = tmp_path / "skills_src"
        self._make_skill(skills_src, "plain", "# Plain\n")
        self._make_skill(skills_src, "gated", "---\nrequires_command: sometool\n---\n")
        agents_dir = tmp_path / "agents"
        vars_path = tmp_path / "vars.json"

        with patch("llm_prompts.install.shutil.which", return_value=None):
            managed = _install_skills(
                [skills_src], agents_dir, "claude-code", vars_path
            )

        plain = agents_dir / "skills" / "plain"
        assert plain.is_dir() and not plain.is_symlink()
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
        vars_path = tmp_path / "vars.json"

        codex_agents = tmp_path / "codex_agents"
        with patch(
            "llm_prompts.install.shutil.which", return_value="/usr/bin/sometool"
        ):
            codex_managed = _install_skills(
                [skills_src], codex_agents, "codex", vars_path
            )

        assert (codex_agents / "skills" / "ask-codex").exists() is False
        assert "ask-codex" not in codex_managed

        cc_agents = tmp_path / "cc_agents"
        with patch(
            "llm_prompts.install.shutil.which", return_value="/usr/bin/sometool"
        ):
            cc_managed = _install_skills(
                [skills_src], cc_agents, "claude-code", vars_path
            )

        ask_codex = cc_agents / "skills" / "ask-codex"
        assert ask_codex.is_dir() and not ask_codex.is_symlink()
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
        vars_path = tmp_path / "vars.json"

        managed = _install_skills(
            [overlay_dir, base_dir], agents_dir, "claude-code", vars_path
        )

        collide = agents_dir / "skills" / "collide"
        assert collide.is_dir() and not collide.is_symlink()
        assert "OVERLAY-COLLIDE" in (collide / "SKILL.md").read_text(encoding="utf-8")
        assert managed == {"shared-only", "collide", "overlay-only"}


class TestInstallPluginSkills:
    def _make_skill(self, parent: Path, name: str, skill_md: str) -> Path:
        skill_dir = parent / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        return skill_dir

    def test_plugin_skill_installed_as_symlink(self, tmp_path: Path) -> None:
        src = self._make_skill(tmp_path / "checkout", "tdd", "# TDD\n")
        agents_dir = tmp_path / "agents"

        managed = _install_plugin_skills(
            [("tdd", src, {})], agents_dir, "claude-code", set()
        )

        dest = agents_dir / "skills" / "tdd"
        assert dest.is_symlink()
        assert dest.resolve() == src.resolve()
        assert "tdd" in managed

    def test_collision_with_managed_skill_is_skipped(self, tmp_path: Path) -> None:
        src = self._make_skill(tmp_path / "checkout", "tdd", "# PLUGIN\n")
        agents_dir = tmp_path / "agents"
        existing = agents_dir / "skills" / "tdd"
        existing.mkdir(parents=True)
        (existing / "SKILL.md").write_text("# BUILTIN\n", encoding="utf-8")

        managed = _install_plugin_skills(
            [("tdd", src, {})], agents_dir, "claude-code", {"tdd"}
        )

        assert existing.is_symlink() is False
        assert (existing / "SKILL.md").read_text(encoding="utf-8") == "# BUILTIN\n"
        assert "tdd" not in managed

    def test_requires_gate_skips_skill(self, tmp_path: Path) -> None:
        src = self._make_skill(
            tmp_path / "checkout", "gated", "---\nrequires_command: sometool\n---\n"
        )
        agents_dir = tmp_path / "agents"

        with patch("llm_prompts.install.shutil.which", return_value=None):
            managed = _install_plugin_skills(
                [("gated", src, {})], agents_dir, "claude-code", set()
            )

        assert (agents_dir / "skills" / "gated").exists() is False
        assert "gated" not in managed

    def test_duplicate_plugin_name_first_wins(self, tmp_path: Path) -> None:
        first = self._make_skill(tmp_path / "a", "dup", "# FIRST\n")
        second = self._make_skill(tmp_path / "b", "dup", "# SECOND\n")
        agents_dir = tmp_path / "agents"

        managed = _install_plugin_skills(
            [("dup", first, {}), ("dup", second, {})],
            agents_dir,
            "claude-code",
            set(),
        )

        dest = agents_dir / "skills" / "dup"
        assert dest.resolve() == first.resolve()
        assert managed == {"dup"}

    def test_override_materializes_directory_no_override_stays_symlink(
        self, tmp_path: Path
    ) -> None:
        src_a = self._make_skill(tmp_path / "checkout", "skill-a", "# a\n")
        src_b = self._make_skill(tmp_path / "checkout", "skill-b", "# b\n")
        agents_dir = tmp_path / "agents"

        managed = _install_plugin_skills(
            [
                ("skill-a", src_a, {"disable-model-invocation": "false"}),
                ("skill-b", src_b, {}),
            ],
            agents_dir,
            "claude-code",
            set(),
        )

        dest_a = agents_dir / "skills" / "skill-a"
        dest_b = agents_dir / "skills" / "skill-b"
        assert dest_a.is_dir() and not dest_a.is_symlink()
        assert dest_b.is_symlink()
        assert managed == {"skill-a", "skill-b"}


class TestMaterializeOverrideSkill:
    def _make_skill(
        self, parent: Path, name: str, skill_md: str, *extra_files: str
    ) -> Path:
        skill_dir = parent / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        for extra in extra_files:
            (skill_dir / extra).write_text("extra", encoding="utf-8")
        return skill_dir

    def test_override_materializes_real_directory_with_patched_skill_md(
        self, tmp_path: Path
    ) -> None:
        src = self._make_skill(
            tmp_path / "checkout",
            "adhd",
            "---\ndisable-model-invocation: true\n---\n\nBody.\n",
        )
        dest = tmp_path / "dest" / "adhd"
        managed: set[str] = set()

        _materialize_override_skill(
            src, dest, {"disable-model-invocation": "false"}, managed
        )

        assert dest.is_dir() and not dest.is_symlink()
        content = (dest / "SKILL.md").read_text(encoding="utf-8")
        assert "disable-model-invocation: false" in content
        assert "adhd" in managed

    def test_sibling_files_symlinked_and_stay_live(self, tmp_path: Path) -> None:
        src = self._make_skill(
            tmp_path / "checkout", "adhd", "# adhd\n", "reference.md"
        )
        dest = tmp_path / "dest" / "adhd"

        _materialize_override_skill(src, dest, {"name": "adhd"}, set())

        sibling = dest / "reference.md"
        assert sibling.is_symlink()
        (src / "reference.md").write_text("changed", encoding="utf-8")
        assert sibling.read_text(encoding="utf-8") == "changed"

    def test_sibling_removed_upstream_is_pruned(self, tmp_path: Path) -> None:
        src = self._make_skill(
            tmp_path / "checkout", "adhd", "# adhd\n", "reference.md"
        )
        dest = tmp_path / "dest" / "adhd"
        _materialize_override_skill(src, dest, {"name": "adhd"}, set())
        assert (dest / "reference.md").exists()

        (src / "reference.md").unlink()
        _materialize_override_skill(src, dest, {"name": "adhd"}, set())

        assert not (dest / "reference.md").exists()

    def test_idempotent_second_run_rewrites_nothing(self, tmp_path: Path) -> None:
        src = self._make_skill(
            tmp_path / "checkout",
            "adhd",
            "---\ndisable-model-invocation: true\n---\n\nBody.\n",
        )
        dest = tmp_path / "dest" / "adhd"
        _materialize_override_skill(
            src, dest, {"disable-model-invocation": "false"}, set()
        )
        before = (dest / "SKILL.md").stat().st_mtime_ns

        _materialize_override_skill(
            src, dest, {"disable-model-invocation": "false"}, set()
        )

        after = (dest / "SKILL.md").stat().st_mtime_ns
        assert before == after

    def test_prior_plain_symlink_converts_to_real_directory(
        self, tmp_path: Path
    ) -> None:
        src = self._make_skill(tmp_path / "checkout", "adhd", "# adhd\n")
        dest = tmp_path / "dest" / "adhd"
        dest.parent.mkdir(parents=True)
        dest.symlink_to(src)

        _materialize_override_skill(src, dest, {"name": "adhd"}, set())

        assert dest.is_dir() and not dest.is_symlink()

    def test_removing_overrides_converts_materialized_dir_back_to_symlink(
        self, tmp_path: Path
    ) -> None:
        src = self._make_skill(tmp_path / "checkout", "adhd", "# adhd\n")
        dest = tmp_path / "dest" / "adhd"
        _materialize_override_skill(src, dest, {"name": "adhd"}, set())
        assert dest.is_dir() and not dest.is_symlink()

        managed: set[str] = set()
        from llm_prompts.install import _install_symlink

        _install_symlink(src, dest, "plugin skill", managed)

        assert dest.is_symlink()
        assert dest.resolve() == src.resolve()


class TestMaterializeBuiltinSkill:
    def _make_skill(
        self, parent: Path, name: str, skill_md: str, *extra_files: str
    ) -> Path:
        skill_dir = parent / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        for extra in extra_files:
            (skill_dir / extra).write_text("extra", encoding="utf-8")
        return skill_dir

    def _write_vars(self, tmp_path: Path, variables: dict[str, str]) -> Path:
        path = tmp_path / "vars.json"
        path.write_text(json.dumps(variables), encoding="utf-8")
        return path

    def test_skill_md_variables_substituted(self, tmp_path: Path) -> None:
        src = self._make_skill(
            tmp_path / "src", "session-end", "# Session end\n\n{{TOOL_COMPLETE}}.\n"
        )
        dest = tmp_path / "dest" / "session-end"
        vars_path = self._write_vars(tmp_path, {"TOOL_COMPLETE": "mark done"})

        _materialize_builtin_skill(src, dest, vars_path, set())

        content = (dest / "SKILL.md").read_text(encoding="utf-8")
        assert "mark done." in content
        assert "{{TOOL_COMPLETE}}" not in content

    def test_frontmatter_intact_after_substitution(self, tmp_path: Path) -> None:
        src = self._make_skill(
            tmp_path / "src",
            "session-end",
            "---\nname: session-end\ndescription: Wrap up.\n---\n\n{{TOOL_COMPLETE}}.\n",
        )
        dest = tmp_path / "dest" / "session-end"
        vars_path = self._write_vars(tmp_path, {"TOOL_COMPLETE": "mark done"})

        _materialize_builtin_skill(src, dest, vars_path, set())

        content = (dest / "SKILL.md").read_text(encoding="utf-8")
        assert "name: session-end" in content
        assert "description: Wrap up." in content

    def test_siblings_still_resolve_and_stay_live(self, tmp_path: Path) -> None:
        src = self._make_skill(
            tmp_path / "src", "tidy-code", "# Tidy code\n", "reference.md"
        )
        dest = tmp_path / "dest" / "tidy-code"
        vars_path = self._write_vars(tmp_path, {})

        _materialize_builtin_skill(src, dest, vars_path, set())

        sibling = dest / "reference.md"
        assert sibling.is_symlink()
        (src / "reference.md").write_text("changed", encoding="utf-8")
        assert sibling.read_text(encoding="utf-8") == "changed"

    def test_companion_script_still_runs(self, tmp_path: Path) -> None:
        src = self._make_skill(tmp_path / "src", "tidy-code", "# Tidy code\n")
        (src / "check.py").write_text("print('ok')\n", encoding="utf-8")
        dest = tmp_path / "dest" / "tidy-code"
        vars_path = self._write_vars(tmp_path, {})

        _materialize_builtin_skill(src, dest, vars_path, set())

        completed = subprocess.run(
            [sys.executable, str(dest / "check.py")],
            capture_output=True,
            text=True,
            check=True,
        )
        assert completed.stdout.strip() == "ok"

    def test_missing_vars_file_defaults_to_no_substitution(
        self, tmp_path: Path
    ) -> None:
        src = self._make_skill(tmp_path / "src", "session-end", "{{TOOL_COMPLETE}}.\n")
        dest = tmp_path / "dest" / "session-end"

        _materialize_builtin_skill(src, dest, tmp_path / "missing-vars.json", set())

        content = (dest / "SKILL.md").read_text(encoding="utf-8")
        assert "{{TOOL_COMPLETE}}" in content


class TestMainValidatesPlugins:
    def test_invalid_plugin_entry_exits_before_touching_disk(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch(
                "llm_prompts.plugins._load_plugins",
                return_value=[{"source": "https://x.git"}],
            ),
            pytest.raises(SystemExit),
        ):
            install_main(["claude-code"])

        assert not (home / ".claude" / "skills").exists()

    def test_frontmatter_overrides_scoped_per_skill_name(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        checkout = tmp_path / "checkout"
        (checkout / "skills" / "skill-a").mkdir(parents=True)
        (checkout / "skills" / "skill-a" / "SKILL.md").write_text(
            "---\ndisable-model-invocation: true\n---\n\nBody.\n", encoding="utf-8"
        )
        (checkout / "skills" / "skill-b").mkdir(parents=True)
        (checkout / "skills" / "skill-b" / "SKILL.md").write_text(
            "---\ndisable-model-invocation: true\n---\n\nBody.\n", encoding="utf-8"
        )

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch(
                "llm_prompts.plugins._load_plugins",
                return_value=[
                    {
                        "name": "multi",
                        "source": "https://x.git",
                        "frontmatter_overrides": {
                            "skill-a": {"disable-model-invocation": False}
                        },
                    }
                ],
            ),
            patch("llm_prompts.plugins.ensure_cloned", return_value=checkout),
        ):
            install_main(["claude-code"])

        dest_a = home / ".claude" / "skills" / "skill-a"
        dest_b = home / ".claude" / "skills" / "skill-b"
        assert dest_a.is_dir() and not dest_a.is_symlink()
        content_a = (dest_a / "SKILL.md").read_text(encoding="utf-8")
        assert "disable-model-invocation: false" in content_a
        assert dest_b.is_symlink()


class TestMainRunsSizeGuard:
    def test_single_violation_does_not_block_other_installs(
        self, tmp_path: Path
    ) -> None:
        from llm_prompts.size_guard import CheckResult

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        failing_result = CheckResult(
            passed=False,
            artifacts=[],
            violations=[self._violation(tmp_path / "coding.md")],
            report="Prompt-size guard failed:\n  [rule_bytes] coding.md ...",
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
        ):
            install_main(["claude-code"])

        assert (home / ".claude" / "skills").exists()

    def test_collection_violation_freezes_only_that_agent(self, tmp_path: Path) -> None:
        from llm_prompts.size_guard import CheckResult, Violation
        from llm_prompts.size_limits import COLLECTION_BYTES

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        violation = Violation(
            metric=COLLECTION_BYTES,
            target="claude-code",
            dest_name="claude-code",
            actual=999_999,
            threshold=50_000,
            source=tmp_path / "claude-code",
        )
        failing_result = CheckResult(
            passed=False, artifacts=[], violations=[violation], report="failed"
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
        ):
            dirs = _get_dirs()
            install_main(["claude-code", "cline"])

        assert not dirs["claude-code"]["rules"].exists()
        assert dirs["cline"]["rules"].exists()

    def test_frozen_agent_logged_at_error_level(self, tmp_path: Path) -> None:
        from llm_prompts.size_guard import CheckResult, Violation
        from llm_prompts.size_limits import COLLECTION_BYTES

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        violation = Violation(
            metric=COLLECTION_BYTES,
            target="claude-code",
            dest_name="claude-code",
            actual=999_999,
            threshold=50_000,
            source=tmp_path / "claude-code",
        )
        failing_result = CheckResult(
            passed=False, artifacts=[], violations=[violation], report="failed"
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
            patch("llm_prompts.install.log") as mock_log,
        ):
            install_main(["claude-code"])

        logged_error = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "error"
        ]
        assert any("claude-code" in line for line in logged_error)

    def test_frozen_agent_makes_result_truthy(self, tmp_path: Path) -> None:
        from llm_prompts.size_guard import CheckResult, Violation
        from llm_prompts.size_limits import COLLECTION_BYTES

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        violation = Violation(
            metric=COLLECTION_BYTES,
            target="claude-code",
            dest_name="claude-code",
            actual=999_999,
            threshold=50_000,
            source=tmp_path / "claude-code",
        )
        failing_result = CheckResult(
            passed=False, artifacts=[], violations=[violation], report="failed"
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
        ):
            result = install_main(["claude-code"])

        assert result is True

    def test_blocking_violation_report_logged_at_error_level(
        self, tmp_path: Path
    ) -> None:
        from llm_prompts.size_guard import CheckResult, format_report

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        violation = self._violation(tmp_path / "a.md")
        failing_result = CheckResult(
            passed=False, artifacts=[], violations=[violation], report="failed"
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
            patch("llm_prompts.install.log") as mock_log,
        ):
            install_main(["claude-code"])

        logged_error = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "error"
        ]
        for line in format_report([violation]).splitlines():
            assert line in logged_error

    def test_skipped_skill_logs_directory_name_not_skill_md(
        self, tmp_path: Path
    ) -> None:
        from llm_prompts.size_guard import CheckResult, Violation
        from llm_prompts.size_limits import SKILL_BODY_BYTES

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        skill_src = tmp_path / "skills" / "big-skill" / "SKILL.md"
        skill_src.parent.mkdir(parents=True)
        skill_src.write_text("Body\n", encoding="utf-8")
        violation = Violation(
            metric=SKILL_BODY_BYTES,
            target="claude-code",
            dest_name="big-skill",
            actual=99_999,
            threshold=5_000,
            source=skill_src,
        )
        failing_result = CheckResult(
            passed=False, artifacts=[], violations=[violation], report="failed"
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
            patch("llm_prompts.install.log") as mock_log,
        ):
            install_main(["claude-code"])

        logged_error = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "error"
        ]
        assert any(
            "big-skill" in line and "SKILL.md" not in line for line in logged_error
        )

    def test_violation_for_one_target_leaves_other_targets_installed(
        self, tmp_path: Path
    ) -> None:
        from llm_prompts.size_guard import CheckResult, Violation

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        overlay_root = tmp_path / "overlay"
        rule_src = _make_rule(
            overlay_root / "shared" / "rules", "shared.md", "new content"
        )
        violation = Violation(
            metric="rule_bytes",
            target="claude-code",
            dest_name="shared.md",
            actual=99_999,
            threshold=5_000,
            source=rule_src,
        )
        failing_result = CheckResult(
            passed=False, artifacts=[], violations=[violation], report="failed"
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths",
                return_value=[overlay_root],
            ),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
        ):
            dirs = _get_dirs()
            install_main(["claude-code", "kiro"])

        assert not (dirs["claude-code"]["rules"] / "shared.md").exists()
        assert "new content" in (dirs["kiro"]["rules"] / "shared.md").read_text(
            encoding="utf-8"
        )

    def test_skipped_prompt_logged_and_returned(self, tmp_path: Path) -> None:
        from llm_prompts.size_guard import CheckResult

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        violation_source = tmp_path / "a.md"
        failing_result = CheckResult(
            passed=False,
            artifacts=[],
            violations=[self._violation(violation_source)],
            report="failed",
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
            patch("llm_prompts.install.log") as mock_log,
        ):
            skipped = install_main(["claude-code"])

        assert skipped is True
        logged_error = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "error"
        ]
        assert any(violation_source.name in line for line in logged_error)

    def test_skipped_prompt_stays_carried_forward_across_repeated_runs(
        self, tmp_path: Path
    ) -> None:
        from llm_prompts.manifest import read_manifest, write_manifest
        from llm_prompts.size_guard import CheckResult

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        overlay_root = tmp_path / "overlay"
        rule_src = _make_rule(
            overlay_root / "shared" / "rules", "synthetic-carry.md", "new content"
        )
        failing_result = CheckResult(
            passed=False,
            artifacts=[],
            violations=[self._violation(rule_src)],
            report="failed",
        )

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths",
                return_value=[overlay_root],
            ),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
        ):
            dest = _get_dirs()["claude-code"]["rules"] / "synthetic-carry.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("old content", encoding="utf-8")
            write_manifest("claude-code", [str(dest)])

            for _ in range(2):
                install_main(["claude-code"])
                assert dest.read_text(encoding="utf-8") == "old content"
                assert str(dest) in read_manifest()["claude-code"]["files"]

    @staticmethod
    def _violation(source: Path) -> Violation:
        return Violation(
            metric="rule_bytes",
            target="claude-code",
            dest_name=source.name,
            actual=99_999,
            threshold=5_000,
            source=source,
        )

    def _install_with_baseline(
        self, tmp_path: Path, violations: list[Violation], baseline: dict[Path, str]
    ) -> tuple[Path, MagicMock]:
        from llm_prompts.size_guard import CheckResult

        home = tmp_path / "home"
        home.mkdir()
        failing_result = CheckResult(
            passed=False, artifacts=[], violations=violations, report="failed"
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", tmp_path / "installed.json"),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
            patch("llm_prompts.install.log") as mock_log,
        ):
            install_main(["claude-code"], size_baseline=baseline)
        return home, mock_log

    def test_violation_in_updated_file_warns_and_installs(self, tmp_path: Path) -> None:
        from llm_prompts.size_guard import snapshot_sources

        src = tmp_path / "src"
        src.mkdir()
        rule_b = src / "b.md"
        rule_b.write_text("old", encoding="utf-8")
        baseline = snapshot_sources([src])
        rule_b.write_text("new and oversized", encoding="utf-8")

        home, mock_log = self._install_with_baseline(
            tmp_path, [self._violation(rule_b)], baseline
        )

        assert (home / ".claude" / "skills").exists()
        levels = {call.args[0] for call in mock_log.call_args_list}
        assert "error" not in levels
        logged_warn = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "warn"
        ]
        assert any("b.md" in line for line in logged_warn)

    def test_untouched_violation_skips_while_pulled_violation_still_installs(
        self, tmp_path: Path
    ) -> None:
        from llm_prompts.size_guard import snapshot_sources

        src = tmp_path / "src"
        src.mkdir()
        rule_a = src / "a.md"
        rule_b = src / "b.md"
        rule_a.write_text("oversized all along", encoding="utf-8")
        rule_b.write_text("old", encoding="utf-8")
        baseline = snapshot_sources([src])
        rule_b.write_text("new and oversized", encoding="utf-8")

        home, mock_log = self._install_with_baseline(
            tmp_path,
            [self._violation(rule_a), self._violation(rule_b)],
            baseline,
        )

        assert (home / ".claude" / "skills").exists()
        logged_warn = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "warn"
        ]
        assert any("b.md" in line for line in logged_warn)

    def test_size_check_passes_for_own_prompts_dir(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
        ):
            install_main(["claude-code"])

        assert (home / ".claude" / "skills").exists()

    def test_passing_check_logs_parked_state_matching_the_shared_helper(
        self, tmp_path: Path
    ) -> None:
        from llm_prompts.size_guard import Artifact, CheckResult, parked_state_lines
        from llm_prompts.size_limits import FINALS, RULE_BYTES

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        artifact = Artifact(
            RULE_BYTES,
            "claude-code",
            "coding.md",
            FINALS[RULE_BYTES] + 1,
            tmp_path / "coding.md",
        )
        passing_result = CheckResult(
            passed=True,
            artifacts=[artifact],
            violations=[],
            report="All prompt-size checks passed.",
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=passing_result),
            patch("llm_prompts.install.log") as mock_log,
        ):
            install_main(["claude-code"])

        # This is the parity the pre-flight and `llm-prompts check` must share:
        # both report a parked schedule through the exact same helper.
        expected_lines = parked_state_lines([artifact])
        assert expected_lines
        logged_info = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "info"
        ]
        for line in expected_lines:
            assert line in logged_info

    def test_declaration_error_aborts_before_touching_disk(
        self, tmp_path: Path
    ) -> None:
        from llm_prompts.size_guard import CheckResult

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        failing_result = CheckResult(
            passed=False,
            artifacts=[],
            violations=[],
            report="Prompt-size allowance declarations invalid:\n"
            "  bad.json: unknown metric 'nope'",
            declaration_errors=["bad.json: unknown metric 'nope'"],
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
            patch("llm_prompts.install.log") as mock_log,
            pytest.raises(SystemExit),
        ):
            install_main(["claude-code"])

        assert not (home / ".claude" / "skills").exists()
        logged_error = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "error"
        ]
        assert any("unknown metric" in line for line in logged_error)

    def test_stale_allowance_logged_without_aborting(self, tmp_path: Path) -> None:
        from llm_prompts.size_guard import CheckResult

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        passing_result = CheckResult(
            passed=True,
            artifacts=[],
            violations=[],
            report="All prompt-size checks passed.",
            stale=["overlay.json: allowance for 'rule_bytes.x.md' is stale"],
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=passing_result),
            patch("llm_prompts.install.log") as mock_log,
        ):
            install_main(["claude-code"])

        assert (home / ".claude" / "skills").exists()
        logged_warn = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "warn"
        ]
        assert any("is stale" in line for line in logged_warn)


class TestCarryForward:
    def test_kept_when_previously_installed(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest.md"
        previous_manifest: dict[str, AgentManifest] = {
            "test-agent": {"files": [str(dest)]}
        }

        kept = _carry_forward("test-agent", dest, "synthetic label", previous_manifest)

        assert kept is True

    def test_kept_logs_expected_message(self) -> None:
        dest = Path("/tmp/dest.md")
        previous_manifest: dict[str, AgentManifest] = {
            "test-agent": {"files": [str(dest)]}
        }

        with patch("llm_prompts.install.log") as mock_log:
            _carry_forward("test-agent", dest, "synthetic label", previous_manifest)

        logged_warn = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "warn"
        ]
        assert any(
            "[test-agent] Kept previous synthetic label: size guard violation" in line
            for line in logged_warn
        )

    def test_not_installed_when_not_previously_installed(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest.md"
        previous_manifest: dict[str, AgentManifest] = {"test-agent": {"files": []}}

        kept = _carry_forward("test-agent", dest, "synthetic label", previous_manifest)

        assert kept is False

    def test_not_installed_logs_expected_message(self) -> None:
        dest = Path("/tmp/dest.md")
        previous_manifest: dict[str, AgentManifest] = {"test-agent": {"files": []}}

        with patch("llm_prompts.install.log") as mock_log:
            _carry_forward("test-agent", dest, "synthetic label", previous_manifest)

        logged_warn = [
            call.args[1] for call in mock_log.call_args_list if call.args[0] == "warn"
        ]
        assert any(
            "[test-agent] Not installed synthetic label: size guard violation" in line
            for line in logged_warn
        )

    def test_no_filesystem_mutation(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest.md"
        previous_manifest: dict[str, AgentManifest] = {
            "test-agent": {"files": [str(dest)]}
        }
        before = set(tmp_path.iterdir())

        _carry_forward("test-agent", dest, "synthetic label", previous_manifest)

        assert set(tmp_path.iterdir()) == before
        assert not dest.exists()


class TestInstallContentSkipSet:
    def test_skipped_rule_left_unchanged(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        rule_src = _make_rule(shared, "a.md", "new content")
        dest_dir = tmp_path / "dest" / "rules"
        dest_dir.mkdir(parents=True)
        dest = dest_dir / "a.md"
        dest.write_text("old content", encoding="utf-8")
        agent = _Agent(
            name="claude-code", root_dir=root, dirs={"claude-code": {"rules": dest_dir}}
        )

        agent.install_rules(
            shared,
            [],
            [],
            skip_set=frozenset({rule_src.resolve()}),
            previous_manifest={},
        )

        assert dest.read_text(encoding="utf-8") == "old content"

    def test_skipped_workflow_left_unchanged(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "workflows"
        workflow_src = _make_rule(shared, "a.md", "new content")
        dest_dir = tmp_path / "dest" / "workflows"
        dest_dir.mkdir(parents=True)
        dest = dest_dir / "a.md"
        dest.write_text("old content", encoding="utf-8")
        agent = _Agent(
            name="claude-code",
            root_dir=root,
            dirs={"claude-code": {"workflows": dest_dir}},
        )

        _install_content(
            agent,
            "workflows",
            shared,
            [],
            [],
            skip_set=frozenset({workflow_src.resolve()}),
            previous_manifest={},
        )

        assert dest.read_text(encoding="utf-8") == "old content"

    def test_skipped_agent_specific_source_left_as_is(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        shared.mkdir(parents=True)
        specific_src = _make_rule(
            root / "claude-code" / "rules", "specific.md", "new specific"
        )
        dest_dir = tmp_path / "dest" / "rules"
        dest_dir.mkdir(parents=True)
        dest = dest_dir / "specific.md"
        dest.write_text("old specific", encoding="utf-8")
        agent = _Agent(
            name="claude-code", root_dir=root, dirs={"claude-code": {"rules": dest_dir}}
        )

        _install_content(
            agent,
            "rules",
            shared,
            [],
            [],
            skip_set=frozenset({specific_src.resolve()}),
            previous_manifest={},
        )

        assert dest.read_text(encoding="utf-8") == "old specific"

    def test_kept_prompt_is_carried_into_managed_set_and_survives_cleanup(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        rule_src = _make_rule(shared, "a.md", "new content")
        dest_dir = tmp_path / "dest" / "rules"
        dest_dir.mkdir(parents=True)
        dest = dest_dir / "a.md"
        dest.write_text("old content", encoding="utf-8")
        agent = _Agent(
            name="claude-code", root_dir=root, dirs={"claude-code": {"rules": dest_dir}}
        )
        previous_manifest: dict[str, AgentManifest] = {
            "claude-code": {"files": [str(dest)]}
        }

        managed = agent.install_rules(
            shared,
            [],
            [],
            skip_set=frozenset({rule_src.resolve()}),
            previous_manifest=previous_manifest,
        )

        assert "a.md" in managed

        _cleanup_stale(
            "claude-code",
            [str(dest_dir / name) for name in managed],
            previous_manifest,
        )
        assert dest.exists()

    def test_skipped_prompt_never_installed_stays_uninstalled(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        rule_src = _make_rule(shared, "a.md", "new content")
        dest_dir = tmp_path / "dest" / "rules"
        agent = _Agent(
            name="claude-code", root_dir=root, dirs={"claude-code": {"rules": dest_dir}}
        )

        managed = agent.install_rules(
            shared,
            [],
            [],
            skip_set=frozenset({rule_src.resolve()}),
            previous_manifest={"claude-code": {"files": []}},
        )

        assert "a.md" not in managed
        assert not (dest_dir / "a.md").exists()

    def test_non_skipped_prompt_installs_current_version(self, tmp_path: Path) -> None:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        _make_rule(shared, "a.md", "current content")
        dest_dir = tmp_path / "dest" / "rules"
        agent = _Agent(
            name="claude-code", root_dir=root, dirs={"claude-code": {"rules": dest_dir}}
        )
        agent.vars_path().parent.mkdir(parents=True)
        agent.vars_path().write_text("{}", encoding="utf-8")

        managed = agent.install_rules(
            shared, [], [], skip_set=frozenset(), previous_manifest={}
        )

        assert "a.md" in managed
        assert "current content" in (dest_dir / "a.md").read_text(encoding="utf-8")


class TestInstallSkillsSkipSet:
    def test_skipped_skill_folder_left_unchanged(self, tmp_path: Path) -> None:
        skills_src = tmp_path / "skills_src"
        skill_dir = skills_src / "my-skill"
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("# New\n", encoding="utf-8")
        agents_dir = tmp_path / "agents"
        installed_skill_dir = agents_dir / "skills" / "my-skill"
        installed_skill_dir.mkdir(parents=True)
        (installed_skill_dir / "SKILL.md").write_text("# Old\n", encoding="utf-8")
        vars_path = tmp_path / "vars.json"

        managed = _install_skills(
            [skills_src],
            agents_dir,
            "test-agent",
            vars_path,
            skip_set=frozenset({skill_md.resolve()}),
            previous_manifest={"test-agent": {"files": [str(installed_skill_dir)]}},
        )

        assert (installed_skill_dir / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "# Old\n"
        assert "my-skill" in managed


class TestInstallAgentsSkipSet:
    def test_skipped_agent_all_variants_left_unchanged(self, tmp_path: Path) -> None:
        agents_src = tmp_path / "agents_src"
        agents_src.mkdir(parents=True)
        agent_src = agents_src / "reasoner.md"
        agent_src.write_text(
            "---\ngenerate_variants: sonnet-high,sonnet-medium\n---\n\nNew body\n",
            encoding="utf-8",
        )
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir(parents=True)
        variant_high = agents_dir / "reasoner-sonnet-high.md"
        variant_medium = agents_dir / "reasoner-sonnet-medium.md"
        variant_high.write_text("OLD VARIANT high", encoding="utf-8")
        variant_medium.write_text("OLD VARIANT medium", encoding="utf-8")
        previous_manifest: dict[str, AgentManifest] = {
            "claude-code": {"files": [str(variant_high), str(variant_medium)]}
        }

        managed = _install_agents(
            [agents_src],
            agents_dir,
            skip_set=frozenset({agent_src.resolve()}),
            previous_manifest=previous_manifest,
        )

        assert variant_high.read_text(encoding="utf-8") == "OLD VARIANT high"
        assert variant_medium.read_text(encoding="utf-8") == "OLD VARIANT medium"
        assert "reasoner-sonnet-high.md" in managed
        assert "reasoner-sonnet-medium.md" in managed


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


class TestSplitFrontmatter:
    def test_returns_none_when_no_frontmatter_block(self) -> None:
        assert split_frontmatter("# Body\n\nsome text\n") is None

    def test_splits_lines_and_body(self) -> None:
        content = "---\nname: foo\ndescription: A thing\n---\n\n# Body\n"
        result = split_frontmatter(content)
        assert result == (["name: foo", "description: A thing"], "\n# Body\n")


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


class TestRenderedAndLinkedContentEquivalence:
    """Guards the render-vs-linked dispatch a measurement tool must replicate exactly.

    Shared sources are rendered (variables substituted); agent-specific sources
    are only stripped of gating keys. `_rendered_content`/`_linked_content` must
    stay byte-identical to what the real install path writes to disk for both.
    """

    def test_rendered_shared_content_matches_install_output(
        self, tmp_path: Path
    ) -> None:
        src = _make_rule(
            tmp_path / "src", "rule.md", "---\ndescription: A rule.\n---\n\nBody.\n"
        )
        vars_path = tmp_path / "vars.json"
        vars_path.write_text("{}", encoding="utf-8")
        dest = tmp_path / "dest" / "rule.md"

        _install_rendered(src, dest, vars_path, "claude-code", "rule")

        assert dest.read_text(encoding="utf-8") == _rendered_content(
            src, vars_path, "claude-code"
        )

    def test_linked_agent_specific_content_matches_install_output(
        self, tmp_path: Path
    ) -> None:
        src = _make_rule(
            tmp_path / "src",
            "shell.md",
            "---\nrequires_env: MY_FLAG\ndescription: Agent-specific.\n---\n\nBody.\n",
        )
        dest = tmp_path / "dest" / "shell.md"

        _install_linked(src, dest, "shell")

        assert dest.read_text(encoding="utf-8") == _linked_content(src)


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


class TestPathsScoping:
    def _render(self, tmp_path: Path, template_body: str, target: str) -> str:
        template = tmp_path / "rule.md"
        template.write_text(template_body, encoding="utf-8")
        vars_file = tmp_path / "vars.json"
        vars_file.write_text("{}", encoding="utf-8")
        return render_template(str(template), str(vars_file), target)

    def test_claude_code_emits_paths_as_yaml_list(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path, "---\npaths: '**/*.py'\n---\n\n# Rule\n", "claude-code"
        )
        assert output.startswith('---\npaths:\n  - "**/*.py"\n---')
        assert output.endswith("\n")

    def test_claude_code_emits_every_glob_in_source_order(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path, "---\npaths: '**/*.py, **/*.pyi'\n---\n\n# Rule\n", "claude-code"
        )
        assert '  - "**/*.py"' in output
        assert '  - "**/*.pyi"' in output
        assert output.index('  - "**/*.py"') < output.index('  - "**/*.pyi"')

    def test_claude_code_unscoped_rule_emits_no_frontmatter(
        self, tmp_path: Path
    ) -> None:
        output = self._render(
            tmp_path, "---\ndescription: A rule\n---\n\n# Rule\n", "claude-code"
        )
        assert "---" not in output
        assert output.endswith("\n")

    def test_copilot_apply_to_derived_from_paths(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path, "---\npaths: '**/*.py'\n---\n\n# Rule\n", "copilot"
        )
        assert "applyTo: '**/*.py'" in output
        assert output.endswith("\n")

    def test_copilot_apply_to_key_overrides_paths(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path,
            "---\npaths: '**/*.py'\ncopilot_apply_to: '**'\n---\n\n# Rule\n",
            "copilot",
        )
        assert "applyTo: '**'" in output
        assert "**/*.py" not in output

    def test_kiro_paths_implies_file_match_inclusion(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path, "---\npaths: '**/*.py'\n---\n\n# Rule\n", "kiro"
        )
        assert "inclusion: fileMatch" in output
        assert "fileMatchPattern: '**/*.py'" in output
        assert output.endswith("\n")

    def test_kiro_explicit_inclusion_overrides_paths(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path,
            "---\nkiro_inclusion: manual\npaths: '**/*.py'\n---\n\n# Rule\n",
            "kiro",
        )
        assert "inclusion: manual" in output
        assert "fileMatchPattern:" not in output

    def test_kiro_multiple_paths_emit_pattern_list(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path, "---\npaths: '**/*.py, **/*.pyi'\n---\n\n# Rule\n", "kiro"
        )
        assert "fileMatchPattern: ['**/*.py', '**/*.pyi']" in output
        assert output.endswith("\n")

    def test_codex_ignores_paths(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path, "---\npaths: '**/*.py'\n---\n\n# Rule\n", "codex"
        )
        assert "---" not in output
        assert output.endswith("\n")

    def test_cline_ignores_paths(self, tmp_path: Path) -> None:
        output = self._render(
            tmp_path, "---\npaths: '**/*.py'\n---\n\n# Rule\n", "cline"
        )
        assert "---" not in output
        assert output.endswith("\n")


class TestShippedTestingRule:
    RULE = (
        Path(__file__).parent.parent / "src/llm_prompts/prompts/shared/rules/testing.md"
    )

    def _globs(self) -> list[str]:
        split = split_frontmatter(self.RULE.read_text(encoding="utf-8"))
        assert split is not None
        frontmatter = resolve_frontmatter(split[0])
        assert frontmatter is not None
        return [p.strip() for p in frontmatter["paths"].split(",") if p.strip()]

    def _render(self, tmp_path: Path, target: str) -> str:
        vars_file = tmp_path / "vars.json"
        vars_file.write_text("{}", encoding="utf-8")
        return render_template(str(self.RULE), str(vars_file), target)

    def test_claude_code_scopes_every_glob(self, tmp_path: Path) -> None:
        output = self._render(tmp_path, "claude-code")
        assert output.startswith("---\npaths:\n")
        for glob in self._globs():
            assert f'  - "{glob}"' in output

    def test_copilot_scopes_every_glob(self, tmp_path: Path) -> None:
        output = self._render(tmp_path, "copilot")
        applied = output.partition("applyTo: '")[2].partition("'")[0]
        for glob in self._globs():
            assert glob in applied

    def test_kiro_scopes_every_glob(self, tmp_path: Path) -> None:
        output = self._render(tmp_path, "kiro")
        assert "inclusion: fileMatch" in output
        for glob in self._globs():
            assert f"'{glob}'" in output


class TestGetSourceForManagedFile:
    def test_resolves_managed_rule_to_its_shared_source(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        root = tmp_path / "root"
        rule_src = root / "shared" / "rules"
        rule_src.mkdir(parents=True)
        (rule_src / "foo.md").write_text("rule body", encoding="utf-8")

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.cli._get_root_dir", return_value=root),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
        ):
            dest = home / ".claude" / "rules" / "foo.md"
            source = get_source_for_managed_file(str(dest))

        assert source == str(rule_src / "foo.md")

    def test_resolves_managed_skill_file_to_its_shared_source(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        root = tmp_path / "root"
        skill_src_dir = root / "shared" / "skills" / "my-skill"
        skill_src_dir.mkdir(parents=True)
        (skill_src_dir / "SKILL.md").write_text("skill body", encoding="utf-8")

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.cli._get_root_dir", return_value=root),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
        ):
            dest = home / ".claude" / "skills" / "my-skill" / "SKILL.md"
            source = get_source_for_managed_file(str(dest))

        assert source == str(skill_src_dir / "SKILL.md")

    def test_returns_none_for_a_path_outside_every_managed_directory(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        root = tmp_path / "root"

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.cli._get_root_dir", return_value=root),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
        ):
            dest = tmp_path / "elsewhere" / "random.md"
            source = get_source_for_managed_file(str(dest))

        assert source is None

    def test_returns_none_when_destination_dir_matches_but_file_is_untracked(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        root = tmp_path / "root"

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.cli._get_root_dir", return_value=root),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
        ):
            dest = home / ".claude" / "rules" / "untracked.md"
            source = get_source_for_managed_file(str(dest))

        assert source is None


class TestSkipFailingPrompt:
    """End-to-end: a real `llm-prompts update` skips only the over-limit prompt."""

    _OVERSIZED_DESCRIPTION = "x" * (FINALS[AGENT_DESCRIPTION_CHARS] + 50)
    _SHORT_DESCRIPTION = "A short synthetic agent description."

    def _write_sources(self, overlay_root: Path, agent_description: str) -> None:
        _make_rule(overlay_root / "shared" / "rules", "synthetic-rule.md", "new rule")
        skill_src = overlay_root / "shared" / "skills" / "synthetic-skill"
        skill_src.mkdir(parents=True, exist_ok=True)
        (skill_src / "SKILL.md").write_text("# Skill\nnew skill\n", encoding="utf-8")
        agent_src = overlay_root / "claude-code" / "agents"
        agent_src.mkdir(parents=True, exist_ok=True)
        (agent_src / "synthetic-agent.md").write_text(
            f"---\ndescription: {agent_description}\n---\nAgent body.\n",
            encoding="utf-8",
        )

    def _seed_previous_install(self, home: Path) -> dict[str, Path]:
        """Write a prior install's dest files and manifest for two agents."""
        from llm_prompts.manifest import write_manifest

        dirs = _get_dirs()
        cline_agents_dir, _ = _get_cline_extra_dirs()
        dest = {
            "cline_rule": dirs["cline"]["rules"] / "synthetic-rule.md",
            "claude_rule": dirs["claude-code"]["rules"] / "synthetic-rule.md",
            "cline_skill": cline_agents_dir / "skills" / "synthetic-skill",
            "claude_skill": home / ".claude" / "skills" / "synthetic-skill",
            "claude_agent": dirs["claude-code"]["agents"] / "synthetic-agent.md",
        }
        for key in ("cline_rule", "claude_rule"):
            dest[key].parent.mkdir(parents=True, exist_ok=True)
            dest[key].write_text("old rule", encoding="utf-8")
        for key in ("cline_skill", "claude_skill"):
            dest[key].mkdir(parents=True, exist_ok=True)
            (dest[key] / "SKILL.md").write_text(
                "# Skill\nold skill\n", encoding="utf-8"
            )
        dest["claude_agent"].parent.mkdir(parents=True, exist_ok=True)
        dest["claude_agent"].write_text("old agent", encoding="utf-8")

        write_manifest("cline", [str(dest["cline_rule"]), str(dest["cline_skill"])])
        write_manifest(
            "claude-code",
            [
                str(dest["claude_rule"]),
                str(dest["claude_skill"]),
                str(dest["claude_agent"]),
            ],
        )
        return dest

    def _run_update(self) -> int | str | None:
        from llm_prompts.cli import main as cli_main

        with (
            patch("sys.argv", ["llm-prompts", "update"]),
            patch("llm_prompts.cli._pull_local_sources", return_value=set()),
            patch("llm_prompts.setup.has_remote_sources", return_value=False),
            patch("llm_prompts.setup.detect_stale_local_tools", return_value=set()),
            patch("llm_prompts.setup.run_setup"),
            patch("llm_prompts.cli._get_installed_commit", return_value=None),
            patch("llm_prompts.cli._restart_memory_service"),
            patch("llm_prompts.cli._auto_migrate_memory_db"),
            patch("llm_prompts.plugins.pull_plugin_sources"),
        ):
            return run_capturing_exit(cli_main)

    def _run_first_update(self, tmp_path: Path) -> dict[str, Any]:
        """Seed a previous install, then run `update` with the agent over-limit."""
        home = tmp_path / "home"
        home.mkdir()
        overlay_root = tmp_path / "overlay"
        manifest_path = tmp_path / "installed.json"

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths",
                return_value=[overlay_root],
            ),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest_path),
        ):
            self._write_sources(overlay_root, self._OVERSIZED_DESCRIPTION)
            dest = self._seed_previous_install(home)
            exit_code = self._run_update()

        return {
            "home": home,
            "overlay_root": overlay_root,
            "manifest_path": manifest_path,
            "dest": dest,
            "exit_code": exit_code,
        }

    def test_over_limit_prompt_present_updates_every_other_prompt(
        self, tmp_path: Path
    ) -> None:
        state = self._run_first_update(tmp_path)
        dest = state["dest"]

        assert dest["cline_rule"].read_text(encoding="utf-8").strip() == "new rule"
        assert dest["claude_rule"].read_text(encoding="utf-8").strip() == "new rule"
        assert (dest["cline_skill"] / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "# Skill\nnew skill\n"
        assert (dest["claude_skill"] / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "# Skill\nnew skill\n"

    def test_over_limit_prompt_stays_at_its_old_version(self, tmp_path: Path) -> None:
        state = self._run_first_update(tmp_path)
        dest = state["dest"]

        assert dest["claude_agent"].read_text(encoding="utf-8") == "old agent"
        assert state["exit_code"] == 1

    def test_bringing_the_prompt_under_the_limit_updates_it_on_the_next_run(
        self, tmp_path: Path
    ) -> None:
        state = self._run_first_update(tmp_path)
        dest = state["dest"]
        overlay_root = state["overlay_root"]

        with (
            patch("llm_prompts.install.Path.home", return_value=state["home"]),
            patch(
                "llm_prompts.install._discover_overlay_paths",
                return_value=[overlay_root],
            ),
            patch("llm_prompts.manifest.MANIFEST_PATH", state["manifest_path"]),
        ):
            self._write_sources(overlay_root, self._SHORT_DESCRIPTION)
            exit_code = self._run_update()

        assert exit_code in (0, None)
        assert dest["claude_agent"].read_text(encoding="utf-8") == (
            f"---\ndescription: {self._SHORT_DESCRIPTION}\n---\nAgent body.\n"
        )
