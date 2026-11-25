"""Tests for the claude-code rules install layout."""

from __future__ import annotations

import json
from collections.abc import Container, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from llm_prompts.install import _AllExcept, _ClaudeAgent
from llm_prompts.install import main as install_main

pytestmark = pytest.mark.usefixtures("bare_tree")


def _make_rule(directory: Path, name: str, content: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


class TestClaudeRulesJoin:
    def _build(self, tmp_path: Path) -> _ClaudeAgent:
        root = tmp_path / "prompts"
        shared = root / "shared" / "rules"
        _make_rule(shared, "coding.md", "# coding\n\ncoding body\n")
        _make_rule(shared, "000-canary.md", "# canary\n\ncanary body\n")
        _make_rule(
            shared,
            "coding-python.md",
            "---\npaths: '**/*.py'\n---\n\n# python\n\npython body\n",
        )
        _make_rule(
            root / "claude-code" / "rules", "shell.md", "# shell\n\nshell body\n"
        )
        (root / "claude-code" / "vars.json").write_text("{}", encoding="utf-8")
        dirs = {"claude-code": {"rules": tmp_path / "home" / ".claude" / "rules"}}
        return _ClaudeAgent(name="claude-code", root_dir=root, dirs=dirs)

    def test_unscoped_rules_join_into_one_file_in_name_order(
        self, tmp_path: Path
    ) -> None:
        agent = self._build(tmp_path)

        agent.install_rules(
            shared_src=agent.root_dir / "shared" / "rules",
            overlay_srcs=[],
            overlay_agent_srcs=[],
        )

        content = (agent.dest_dir("rules") / "llm-prompts.md").read_text("utf-8")
        assert content.index("canary body") < content.index("coding body")
        assert content.index("coding body") < content.index("shell body")
        assert "python body" not in content
        assert "---" not in content

    def test_path_scoped_rule_stays_its_own_file(self, tmp_path: Path) -> None:
        agent = self._build(tmp_path)

        installed = agent.install_rules(
            shared_src=agent.root_dir / "shared" / "rules",
            overlay_srcs=[],
            overlay_agent_srcs=[],
        )

        rules_dir = agent.dest_dir("rules")
        assert installed == {"llm-prompts.md", "coding-python.md"}
        assert sorted(p.name for p in rules_dir.iterdir()) == sorted(installed)
        assert (
            (rules_dir / "coding-python.md")
            .read_text("utf-8")
            .startswith("---\npaths:")
        )


def _owning(*paths: Path) -> dict[str, Any]:
    return {"claude-code": {"files": [str(p) for p in paths]}}


class TestClaudeBundleOwnership:
    def _install(
        self,
        agent: _ClaudeAgent,
        skip_set: Container[Path] = frozenset(),
        previous: dict[str, Any] | None = None,
    ) -> set[str]:
        return agent.install_rules(
            agent.root_dir / "shared" / "rules",
            [],
            [],
            skip_set,
            previous,
        )

    def _agent(self, tmp_path: Path, scoped_name: str = "scoped.md") -> _ClaudeAgent:
        agent = TestClaudeRulesJoin()._build(tmp_path)
        _make_rule(
            agent.root_dir / "shared" / "rules",
            scoped_name,
            "---\npaths: '**/*.md'\n---\n\n# scoped\n\nscoped body\n",
        )
        return agent

    def test_untracked_bundle_path_is_never_overwritten(self, tmp_path: Path) -> None:
        agent = self._agent(tmp_path)
        bundle = agent.dest_dir("rules") / "llm-prompts.md"
        _make_rule(bundle.parent, "llm-prompts.md", "mine")

        with pytest.raises(RuntimeError, match="llm-prompts.md"):
            self._install(agent)

        assert bundle.read_text("utf-8") == "mine"

    def test_tracked_bundle_is_replaced(self, tmp_path: Path) -> None:
        agent = self._agent(tmp_path)
        bundle = agent.dest_dir("rules") / "llm-prompts.md"
        _make_rule(bundle.parent, "llm-prompts.md", "old bundle")

        self._install(agent, previous=_owning(bundle))

        assert "canary body" in bundle.read_text("utf-8")

    def test_unscoped_rule_cannot_take_the_bundle_name_in_an_only_install(
        self, tmp_path: Path
    ) -> None:
        agent = self._agent(tmp_path)
        shared = agent.root_dir / "shared" / "rules"
        edited = _make_rule(shared, "llm-prompts.md", "# mine\n\nmine body\n")

        with pytest.raises(RuntimeError, match="llm-prompts.md"):
            self._install(agent, skip_set=_AllExcept(frozenset({edited.resolve()})))

        assert not (agent.dest_dir("rules") / "llm-prompts.md").exists()

    def test_bundle_name_is_reserved_in_any_letter_case(self, tmp_path: Path) -> None:
        agent = self._agent(tmp_path, scoped_name="LLM-Prompts.md")

        with pytest.raises(RuntimeError, match="llm-prompts.md"):
            self._install(agent)

    def test_path_scoped_rule_cannot_take_the_bundle_name(self, tmp_path: Path) -> None:
        agent = self._agent(tmp_path, scoped_name="llm-prompts.md")

        with pytest.raises(RuntimeError, match="llm-prompts.md"):
            self._install(agent)

        assert not (agent.dest_dir("rules") / "llm-prompts.md").exists()


class TestClaudeUpgradeWithHeldBackRule:
    @pytest.fixture(autouse=True)
    def _cache(self, tmp_path: Path) -> Iterator[None]:
        with patch(
            "llm_prompts.manifest.rendered_rules_dir", return_value=tmp_path / "cache"
        ):
            yield

    def _setup(self, tmp_path: Path) -> tuple[_ClaudeAgent, Path, Path]:
        agent = TestClaudeRulesJoin()._build(tmp_path)
        rules_dir = agent.dest_dir("rules")
        old = _make_rule(rules_dir, "coding.md", "old coding")
        held = agent.root_dir / "shared" / "rules" / "coding.md"
        return agent, old, held

    def test_old_per_rule_files_stay_when_a_rule_cannot_be_bundled(
        self, tmp_path: Path
    ) -> None:
        agent, old, held = self._setup(tmp_path)

        installed = agent.install_rules(
            held.parent,
            [],
            [],
            frozenset({held.resolve()}),
            _owning(old),
        )

        assert old.read_text("utf-8") == "old coding"
        assert "coding.md" in installed
        assert "llm-prompts.md" not in installed
        assert not (old.parent / "llm-prompts.md").exists()

    def test_old_files_stay_when_a_rule_fails_to_render(self, tmp_path: Path) -> None:
        agent, old, held = self._setup(tmp_path)
        held.write_text("# coding\n\n{% if %}\n", encoding="utf-8")

        installed = agent.install_rules(held.parent, [], [], frozenset(), _owning(old))

        assert old.read_text("utf-8") == "old coding"
        assert "coding.md" in installed
        assert "llm-prompts.md" not in installed

    def test_old_files_stay_when_the_bundle_cannot_be_written(
        self, tmp_path: Path
    ) -> None:
        agent, old, held = self._setup(tmp_path)

        with patch("llm_prompts.install._write_if_changed"):
            installed = agent.install_rules(
                held.parent, [], [], frozenset(), _owning(old)
            )

        assert "coding.md" in installed
        assert "llm-prompts.md" not in installed

    def test_only_install_defers_the_migration_to_a_full_install(
        self, tmp_path: Path
    ) -> None:
        agent, old, held = self._setup(tmp_path)
        kept = agent.root_dir / "shared" / "rules" / "000-canary.md"

        installed = agent.install_rules(
            held.parent, [], [], _AllExcept(frozenset({kept.resolve()})), _owning(old)
        )

        assert "coding.md" in installed
        assert "llm-prompts.md" not in installed
        assert not (old.parent / "llm-prompts.md").exists()

    def test_migration_completes_once_every_rule_can_be_bundled(
        self, tmp_path: Path
    ) -> None:
        agent, old, held = self._setup(tmp_path)

        installed = agent.install_rules(held.parent, [], [], frozenset(), _owning(old))

        assert "llm-prompts.md" in installed
        assert "coding.md" not in installed


@pytest.fixture
def claude_home(tmp_path: Path) -> Iterator[Path]:
    home = tmp_path / "home"
    home.mkdir()
    with (
        patch("llm_prompts.install.Path.home", return_value=home),
        patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
        patch("llm_prompts.install._running_as_installed_tool", return_value=True),
    ):
        yield home


class TestClaudeInstallLayout:
    def test_reinstall_replaces_per_rule_files_the_manifest_lists(
        self, claude_home: Path, isolated_config_dir: Path
    ) -> None:
        rules_dir = claude_home / ".claude" / "rules"
        old = rules_dir / "old-rule.md"
        mine = rules_dir / "mine.md"
        rules_dir.mkdir(parents=True)
        old.write_text("old", encoding="utf-8")
        mine.write_text("mine", encoding="utf-8")
        manifest = isolated_config_dir / "installed.json"
        manifest.write_text(
            json.dumps({"agents": {"claude-code": {"files": [str(old)]}}}),
            encoding="utf-8",
        )

        install_main(["claude-code"])

        assert not old.exists()
        assert mine.read_text(encoding="utf-8") == "mine"
        assert (rules_dir / "llm-prompts.md").is_file()
        recorded = json.loads(manifest.read_text(encoding="utf-8"))["agents"]
        assert str(rules_dir / "llm-prompts.md") in recorded["claude-code"]["files"]


class TestClaudeOnlyInstall:
    @pytest.fixture(autouse=True)
    def _cache(self, tmp_path: Path) -> Iterator[None]:
        with patch(
            "llm_prompts.manifest.rendered_rules_dir", return_value=tmp_path / "cache"
        ):
            yield

    def _only_coding(
        self, tmp_path: Path, previous: dict[str, Any] | None
    ) -> tuple[Path, set[str]]:
        agent = TestClaudeRulesJoin()._build(tmp_path)
        shared = agent.root_dir / "shared" / "rules"
        edited = shared / "coding.md"
        edited.write_text("# coding\n\nnew coding\n", encoding="utf-8")
        skip = _AllExcept(frozenset({edited.resolve()}))
        installed = agent.install_rules(shared, [], [], skip, previous)
        return agent.dest_dir("rules"), installed

    def test_without_legacy_files_it_still_bundles_nothing(
        self, tmp_path: Path
    ) -> None:
        rules_dir, installed = self._only_coding(tmp_path, None)

        assert "llm-prompts.md" not in installed
        assert not (rules_dir / "llm-prompts.md").exists()
        assert "new coding" in (rules_dir / "coding.md").read_text("utf-8")
        assert not (rules_dir / "000-canary.md").exists()

    def test_the_selected_legacy_rule_is_still_updated(self, tmp_path: Path) -> None:
        agent = TestClaudeRulesJoin()._build(tmp_path)
        old = _make_rule(agent.dest_dir("rules"), "coding.md", "old coding")

        rules_dir, installed = self._only_coding(tmp_path, _owning(old))

        assert "new coding" in (rules_dir / "coding.md").read_text("utf-8")
        assert "coding.md" in installed
        assert "llm-prompts.md" not in installed
