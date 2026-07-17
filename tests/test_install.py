"""Tests for env-gated rule installation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from llm_prompts.install import (
    _Agent,
    _collect_content_srcs,
    _env_var_set,
    _passes_env_gate,
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


class TestPassesEnvGate:
    def test_true_when_no_frontmatter(self, tmp_path: Path) -> None:
        rule = _make_rule(tmp_path, "rule.md", "# Rule\n\nbody\n")
        assert _passes_env_gate(rule) is True

    def test_true_when_required_env_is_set(self, tmp_path: Path) -> None:
        rule = _make_rule(
            tmp_path,
            "rule.md",
            "---\nrequires_env: MY_FLAG\n---\n\n# Rule\n",
        )
        with patch.dict("os.environ", {"MY_FLAG": "1"}):
            assert _passes_env_gate(rule) is True

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
            assert _passes_env_gate(rule) is False


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

        with patch.dict("os.environ", {}, clear=True), patch(
            "llm_prompts.install.Path.home", return_value=tmp_path / "home"
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
