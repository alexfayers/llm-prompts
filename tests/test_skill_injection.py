"""Tests for the skill startup blocks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_prompts.skill_injection import SkillStartupBlocks


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
    def test_flagged_skills_become_blocks_holding_their_installed_body_and_others_give_none(
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
        assert blocks[0].title == "skill `alpha`"
        assert blocks[0].replaces == "load the `alpha` skill"
        assert blocks[0].order == 10

    def test_nothing_is_contributed_without_a_frontend(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        install: Callable[[list[Path]], None],
    ) -> None:
        install([tmp_path / "missing"])
        monkeypatch.setattr(
            "llm_prompts.skill_injection.get_protocol",
            lambda: SimpleNamespace(frontend_spec=None),
        )

        assert SkillStartupBlocks().startup_blocks(["/ws"]) == []
