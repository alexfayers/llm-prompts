"""Tests that the pi-help skill names everything llm-prompts installs or seeds for pi."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_PI_PROMPTS = Path(__file__).parent.parent / "src" / "llm_prompts" / "prompts" / "pi"
_PI_HELP = (_PI_PROMPTS / "skills" / "pi-help" / "SKILL.md").read_text()
_SEED_DIR = _PI_PROMPTS / "seed"


def _package_names() -> list[str]:
    packages = json.loads((_PI_PROMPTS / "settings.json").read_text())["packages"]
    sources = [p if isinstance(p, str) else p["source"] for p in packages]
    return [
        source.removeprefix("npm:").rsplit("@", 1)[0].rsplit("/", 1)[-1]
        for source in sources
    ]


@pytest.mark.parametrize(
    "extension", sorted((_PI_PROMPTS / "extensions").glob("*.ts")), ids=lambda p: p.name
)
def test_pi_help_names_each_installed_extension(extension: Path) -> None:
    assert extension.stem in _PI_HELP


@pytest.mark.parametrize(
    "seed",
    sorted(
        p.relative_to(_SEED_DIR).as_posix() for p in _SEED_DIR.rglob("*") if p.is_file()
    ),
)
def test_pi_help_names_each_seed_config(seed: str) -> None:
    assert seed in _PI_HELP


@pytest.mark.parametrize("package", _package_names())
def test_pi_help_names_each_managed_package(package: str) -> None:
    assert package in _PI_HELP
