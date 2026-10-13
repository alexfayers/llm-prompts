"""Tests for the skill startup blocks."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_prompts.render_template import nested_frontmatter
from llm_prompts.skill_injection import SkillStartupBlocks


class TestNestedFrontmatter:
    def test_reads_the_indented_keys_under_a_parent_key(self) -> None:
        lines = [
            "name: demo",
            "metadata:",
            "  inject_at_start: true",
            "  inject_resume: 'false'",
            "description: other",
        ]

        assert nested_frontmatter(lines, "metadata") == {
            "inject_at_start": "true",
            "inject_resume": "false",
        }

    def test_a_missing_parent_key_gives_nothing(self) -> None:
        assert nested_frontmatter(["name: demo"], "metadata") == {}


def write_skill(skills_dir: Path, name: str, metadata: str, body: str) -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: demo\n{metadata}---\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Path]], None]:
    """Make the plugin see an active frontend whose manifest lists the given skill dirs."""

    def _install(skill_dirs: list[Path]) -> None:
        monkeypatch.setattr(
            "llm_prompts.skill_injection.get_protocol",
            lambda: SimpleNamespace(frontend_spec=SimpleNamespace(name="pi")),
        )
        monkeypatch.setattr(
            "llm_prompts.skill_injection.read_manifest",
            lambda: {"pi": {"files": [str(d) for d in skill_dirs]}},
        )

    return _install


class TestSkillStartupBlocks:
    def test_a_flagged_skill_becomes_a_block_holding_its_installed_body(
        self, tmp_path: Path, install: Callable[[list[Path]], None]
    ) -> None:
        flagged = write_skill(
            tmp_path, "alpha", "metadata:\n  inject_at_start: true\n", "ALPHA BODY"
        )
        install([flagged])

        (block,) = SkillStartupBlocks().startup_blocks(["/ws"])

        assert block.title == "skill `alpha`"
        assert block.replaces == "load the `alpha` skill"
        assert block.skill == "alpha"
        assert block.order == 10
        assert block.body(None) == "ALPHA BODY"
        assert block.body(5) == "ALPHA BODY"
        assert (block.subagents, block.on_resume) == (False, False)

    def test_each_skill_keeps_its_own_body_and_unflagged_skills_give_no_block(
        self, tmp_path: Path, install: Callable[[list[Path]], None]
    ) -> None:
        flagged = "metadata:\n  inject_at_start: true\n"
        install(
            [
                write_skill(tmp_path, "alpha", flagged, "ALPHA BODY"),
                write_skill(tmp_path, "beta", flagged, "BETA BODY"),
                write_skill(tmp_path, "gamma", "", "GAMMA BODY"),
                write_skill(
                    tmp_path,
                    "delta",
                    "metadata:\n  inject_at_start: false\n",
                    "DELTA BODY",
                ),
            ]
        )

        blocks = SkillStartupBlocks().startup_blocks(["/ws"])

        assert {b.skill: b.body(None) for b in blocks} == {
            "alpha": "ALPHA BODY",
            "beta": "BETA BODY",
        }

    def test_the_subagent_and_resume_flags_reach_the_block(
        self, tmp_path: Path, install: Callable[[list[Path]], None]
    ) -> None:
        metadata = "metadata:\n  inject_at_start: true\n  inject_subagents: true\n  inject_resume: true\n"
        install([write_skill(tmp_path, "alpha", metadata, "ALPHA BODY")])

        (block,) = SkillStartupBlocks().startup_blocks(["/ws"])

        assert (block.subagents, block.on_resume) == (True, True)

    def test_nothing_is_contributed_without_a_frontend_a_manifest_entry_or_a_skill_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        install: Callable[[list[Path]], None],
    ) -> None:
        install([tmp_path / "missing"])
        assert SkillStartupBlocks().startup_blocks(["/ws"]) == []

        monkeypatch.setattr("llm_prompts.skill_injection.read_manifest", dict)
        assert SkillStartupBlocks().startup_blocks(["/ws"]) == []

        monkeypatch.setattr(
            "llm_prompts.skill_injection.get_protocol",
            lambda: SimpleNamespace(frontend_spec=None),
        )
        assert SkillStartupBlocks().startup_blocks(["/ws"]) == []

    @pytest.mark.parametrize(
        "workspace", ["no_roots", "plain", "empty_git_repo", "missing"]
    )
    def test_flagged_skills_are_contributed_whatever_the_workspace_roots_are(
        self,
        tmp_path: Path,
        install: Callable[[list[Path]], None],
        workspace: str,
    ) -> None:
        install(
            [
                write_skill(
                    tmp_path / "skills",
                    "alpha",
                    "metadata:\n  inject_at_start: true\n",
                    "ALPHA BODY",
                )
            ]
        )
        root = tmp_path / workspace
        if workspace != "missing":
            root.mkdir()
        if workspace == "empty_git_repo":
            subprocess.run(["git", "init", "-q", str(root)], check=True)
        roots = [] if workspace == "no_roots" else [str(root)]

        (block,) = SkillStartupBlocks().startup_blocks(roots)

        assert block.body(None) == "ALPHA BODY"
