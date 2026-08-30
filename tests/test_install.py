"""Tests for env-gated rule installation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts.install import (
    _GATING_FRONTMATTER_KEYS,
    _Agent,
    _collect_content_srcs,
    _env_var_set,
    _excluded_targets,
    _install_linked,
    _install_plugin_skills,
    _install_rendered,
    _install_skills,
    _linked_content,
    _materialize_builtin_skill,
    _materialize_override_skill,
    _passes_requires_gate,
    _rendered_content,
)
from llm_prompts.install import main as install_main
from llm_prompts.render_template import (
    render_template,
    resolve_frontmatter,
    split_frontmatter,
    strip_gating_keys,
)


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
    def test_size_violation_exits_before_touching_disk(self, tmp_path: Path) -> None:
        from llm_prompts.size_guard import CheckResult, Violation

        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        violation = Violation(
            metric="rule_bytes",
            target="claude-code",
            dest_name="coding.md",
            actual=99_999,
            threshold=5_000,
            source=tmp_path / "coding.md",
        )
        failing_result = CheckResult(
            passed=False,
            artifacts=[],
            violations=[violation],
            report="Prompt-size guard failed:\n  [rule_bytes] coding.md ...",
        )
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
            patch("llm_prompts.manifest.MANIFEST_PATH", manifest),
            patch("llm_prompts.size_guard.check", return_value=failing_result),
            pytest.raises(SystemExit),
        ):
            install_main(["claude-code"])

        assert not (home / ".claude" / "skills").exists()

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

    def test_claude_code_emits_every_glob_in_source_order(
        self, tmp_path: Path
    ) -> None:
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
        output = self._render(tmp_path, "---\npaths: '**/*.py'\n---\n\n# Rule\n", "kiro")
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
        Path(__file__).parent.parent
        / "src/llm_prompts/prompts/shared/rules/testing.md"
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
