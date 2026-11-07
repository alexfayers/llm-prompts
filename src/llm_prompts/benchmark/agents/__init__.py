"""The agents the benchmark can run."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from llm_prompts.benchmark.agents.adapter import AgentAdapter
from llm_prompts.benchmark.agents.claude import ClaudeAdapter
from llm_prompts.benchmark.agents.pi import PiAdapter
from llm_prompts.benchmark.types import Agent

AGENTS: Mapping[Agent, AgentAdapter] = MappingProxyType(
    {"claude": ClaudeAdapter(), "pi": PiAdapter()}
)
DEFAULT_MODELS: Mapping[Agent, str] = MappingProxyType(
    {name: agent.default_model for name, agent in AGENTS.items()}
)
