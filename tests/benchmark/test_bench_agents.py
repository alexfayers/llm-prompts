from typing import get_args

from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.types import Agent


def test_agent_names_match_the_registered_adapters() -> None:
    assert set(get_args(Agent)) == set(AGENTS)
