"""The agents the benchmark can run."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType

from llm_prompts.benchmark.agents.adapter import AgentAdapter
from llm_prompts.benchmark.agents.claude import ClaudeAdapter
from llm_prompts.benchmark.agents.pi import PiAdapter
from llm_prompts.benchmark.types import Agent

AGENTS: Mapping[Agent, AgentAdapter] = MappingProxyType(
    {"claude": ClaudeAdapter(), "pi": PiAdapter()}
)


class _DefaultModels(Mapping[Agent, str]):
    """Each agent's default model, read from its settings when asked for."""

    def __getitem__(self, agent: Agent) -> str:
        return AGENTS[agent].default_model

    def __contains__(self, agent: object) -> bool:
        return agent in AGENTS

    def __iter__(self) -> Iterator[Agent]:
        return iter(AGENTS)

    def __len__(self) -> int:
        return len(AGENTS)


DEFAULT_MODELS: Mapping[Agent, str] = _DefaultModels()
