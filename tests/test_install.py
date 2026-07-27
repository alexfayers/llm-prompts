"""Tests for env-gated rule installation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from llm_prompts.install import (
    _Agent,
    _collect_content_srcs,
    _env_var_set,
    _excluded_targets,
    _install_skills,
    _passes_requires_gate,
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

    def test_requires_command_unsatisfied_skill_not_symlinked(
        self, tmp_path: Path
    ) -> None:
        skills_src = tmp_path / "skills_src"
        self._make_skill(skills_src, "plain", "# Plain\n")
        self._make_skill(skills_src, "gated", "---\nrequires_command: sometool\n---\n")
        agents_dir = tmp_path / "agents"
        managed: set[str] = set()

        with patch("llm_prompts.install.shutil.which", return_value=None):
            _install_skills(skills_src, agents_dir, managed, "claude-code")

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
        codex_managed: set[str] = set()
        with patch(
            "llm_prompts.install.shutil.which", return_value="/usr/bin/sometool"
        ):
            _install_skills(skills_src, codex_agents, codex_managed, "codex")

        assert (codex_agents / "skills" / "ask-codex").exists() is False
        assert "ask-codex" not in codex_managed

        cc_agents = tmp_path / "cc_agents"
        cc_managed: set[str] = set()
        with patch(
            "llm_prompts.install.shutil.which", return_value="/usr/bin/sometool"
        ):
            _install_skills(skills_src, cc_agents, cc_managed, "claude-code")

        assert (cc_agents / "skills" / "ask-codex").is_symlink() is True
        assert "ask-codex" in cc_managed
