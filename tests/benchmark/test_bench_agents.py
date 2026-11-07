import json
from pathlib import Path
from typing import get_args

from llm_prompts.benchmark.agents import AGENTS
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
