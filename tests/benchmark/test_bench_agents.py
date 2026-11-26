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


def test_pi_drops_the_test_output_fold_extension_only_when_the_feature_is_off(
    tmp_path: Path,
) -> None:
    extension = tmp_path / ".pi/agent/extensions/test-output-fold.ts"
    extension.parent.mkdir(parents=True)
    extension.write_text("")

    AGENTS["pi"].install_features(tmp_path, {"test-output-fold": True})
    assert extension.exists()

    AGENTS["pi"].install_features(tmp_path, {"test-output-fold": False})
    assert not extension.exists()


@pytest.mark.parametrize("warm", [True, False])
def test_pi_installs_the_fork_mode_extension_only_when_the_warm_fork_is_measured(
    tmp_path: Path, warm: bool
) -> None:
    agent_dir = tmp_path / ".pi/agent"
    mode = agent_dir / "bench-fork-mode.json"

    AGENTS["pi"].install_features(tmp_path, {"test-output-fold": True})
    assert not mode.exists()

    AGENTS["pi"].install_features(tmp_path, {"warm-fork": warm})
    assert json.loads(mode.read_text()) == {"warm": warm}
    assert (agent_dir / "extensions/bench-fork-mode.ts").read_text().startswith("//")


def test_pi_names_the_model_of_the_cold_workers_only_when_measuring_shared_tasks(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / ".pi/agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "settings.json").write_text(json.dumps({"defaultProvider": "prov"}))
    tiers = agent_dir / "pi-context/models.json"

    AGENTS["pi"].install_features(tmp_path, {"consult": True})
    assert not tiers.exists()

    AGENTS["pi"].install_features(tmp_path, {"shared-tasks": False})
    assert json.loads(tiers.read_text()) == {"bench": "prov/test-model"}


def test_pi_turns_cache_warming_off_only_when_the_feature_is_off(
    tmp_path: Path,
) -> None:
    settings = tmp_path / ".pi/agent/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"cacheWarming": "idle"}))

    AGENTS["pi"].install_features(tmp_path, {"cache-warming": True})
    assert json.loads(settings.read_text())["cacheWarming"] == "idle"

    AGENTS["pi"].install_features(tmp_path, {"cache-warming": False})
    assert json.loads(settings.read_text())["cacheWarming"] == "off"


def test_pi_models_come_from_the_pi_settings() -> None:
    assert AGENTS["pi"].default_model == "test-model"
    assert AGENTS["pi"].judge_model == "test-model"
    assert DEFAULT_MODELS["pi"] == "test-model"


def test_pi_judge_model_is_an_inference_profile_for_a_bare_bedrock_id() -> None:
    pi_settings_path().write_text('{"defaultModel": "anthropic.claude-opus-5-5"}')

    assert AGENTS["pi"].judge_model == "global.anthropic.claude-opus-5-5"


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
