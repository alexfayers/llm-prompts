"""Tests for merging llm-prompts' Herdr settings into the user's config.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from llm_prompts.herdr_config import HerdrConfigError, mute_agent_sound

_CONFIG = """\
onboarding = false

[ui.toast]
delivery = "terminal"  # keep

[ui.sound]
enabled = true

# >>> plugin block
[theme.custom]
active_row_bg = "#414868"
# <<< plugin block
"""


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(_CONFIG, encoding="utf-8")
    return path


def _backup(config: Path) -> Path:
    return config.with_name("config.toml.bak-pi-notify")


def test_muting_an_agent_adds_the_key_and_leaves_the_rest_untouched(
    config: Path,
) -> None:
    assert mute_agent_sound(config, "pi") is True
    text = config.read_text(encoding="utf-8")
    assert text.startswith(_CONFIG)
    assert tomllib.loads(text)["ui"]["sound"] == {
        "enabled": True,
        "agents": {"pi": "off"},
    }
    assert _backup(config).read_text(encoding="utf-8") == _CONFIG


def test_muting_twice_changes_nothing_the_second_time(config: Path) -> None:
    mute_agent_sound(config, "pi")
    first = config.read_text(encoding="utf-8")
    _backup(config).unlink()
    assert mute_agent_sound(config, "pi") is False
    assert config.read_text(encoding="utf-8") == first
    assert not _backup(config).exists()


def test_an_existing_agents_table_gets_the_key_without_losing_others(
    config: Path,
) -> None:
    config.write_text(
        _CONFIG + '\n[ui.sound.agents]\n# keep\ndroid = "off"\n', encoding="utf-8"
    )
    assert mute_agent_sound(config, "pi") is True
    text = config.read_text(encoding="utf-8")
    assert "# keep" in text
    assert tomllib.loads(text)["ui"]["sound"]["agents"] == {
        "droid": "off",
        "pi": "off",
    }


def test_a_value_the_user_already_set_is_kept(config: Path) -> None:
    original = _CONFIG + '\n[ui.sound.agents]\npi = "on"\n'
    config.write_text(original, encoding="utf-8")
    assert mute_agent_sound(config, "pi") is False
    assert config.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "text",
    [
        "this is = = not toml",
        '[ui.sound]\nagents = { droid = "off" }\n',
        "[ui]\nsound = true\n",
    ],
    ids=["invalid", "inline-table", "not-a-table"],
)
def test_a_config_that_cannot_take_the_key_is_left_alone(
    config: Path, text: str
) -> None:
    config.write_text(text, encoding="utf-8")
    with pytest.raises(HerdrConfigError):
        mute_agent_sound(config, "pi")
    assert config.read_text(encoding="utf-8") == text
    assert not _backup(config).exists()
