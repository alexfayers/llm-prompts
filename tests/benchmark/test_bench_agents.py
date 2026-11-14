import json
from pathlib import Path
from typing import get_args

import pytest

from benchmark.conftest import pi_settings_path
from llm_prompts.benchmark.agents import AGENTS, DEFAULT_MODELS
from llm_prompts.benchmark.agents.adapter import ModelNotSet
from llm_prompts.benchmark.types import Agent


def test_agent_names_match_the_registered_adapters() -> None:
    assert set(get_args(Agent)) == set(AGENTS)


def test_pi_template_permits_edits_to_prompt_files_and_keeps_the_other_asks(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".pi/agent/extensions/pi-permission-system/config.json"
    config.parent.mkdir(parents=True)
    asks = {"*": "allow", "*/rules/*.md": "ask", "*/skills/*.md": "ask"}
    config.write_text(
        json.dumps(
            {
                "permission": {
                    "bash": {"*": "allow", "git push *": "ask"},
                    "edit": asks,
                    "write": asks,
                    "path_write": asks,
                }
            }
        )
    )

    AGENTS["pi"].install_guard(tmp_path)

    permission = json.loads(config.read_text())["permission"]
    assert permission["bash"]["git push *"] == "ask"
    for tool in ("edit", "write", "path_write"):
        assert permission[tool] == {"*": "allow"}


def test_pi_models_come_from_the_pi_settings() -> None:
    assert AGENTS["pi"].default_model == "test-model"
    assert AGENTS["pi"].judge_model == "test-model"
    assert DEFAULT_MODELS["pi"] == "test-model"


@pytest.mark.parametrize("settings", [None, "{}", '{"defaultModel": ""}', "[]"])
def test_pi_without_a_default_model_fails_naming_the_setting(
    settings: str | None,
) -> None:
    if settings is None:
        pi_settings_path().unlink()
    else:
        pi_settings_path().write_text(settings)

    for name in ("default_model", "judge_model"):
        with pytest.raises(ModelNotSet, match=r"defaultModel.*settings\.json"):
            getattr(AGENTS["pi"], name)
