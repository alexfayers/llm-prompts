"""What the benchmark needs from an agent."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from llm_prompts.benchmark.types import PreparedCell, Scenario, Session, Trace

GUARD_ARGV = [sys.executable, "-m", "llm_prompts.benchmark.guard.claude"]


class VariantBuildError(Exception):
    def __init__(self, ref: str, reason: str) -> None:
        super().__init__(f"{ref}: {reason}")
        self.ref = ref
        self.reason = reason


class AgentAdapter(Protocol):
    """Everything agent specific: its command and output, its home layout and its judge."""

    template_name: str
    default_model: str
    judge_model: str
    cumulative_cost: bool
    delegation: bool
    shared_dirs: tuple[Path, ...]
    git_packages: Path | None

    def command(
        self,
        prepared: PreparedCell,
        scenario: Scenario,
        model: str,
        session: Session | None = None,
    ) -> list[str]:
        """Return the argv that runs the agent on the scenario, in a saved session when given."""

    def replied(self, line: str) -> bool:
        """Return whether a streamed output line is an assistant reply."""

    def tool_started(self, line: str) -> str | None:
        """Return the tool name a streamed output line starts, if any."""

    def parse(self, lines: Iterable[tuple[float, str]], wall_s: float) -> Trace:
        """Build a trace from the timestamped output lines."""

    def point_memory(self, home: Path, url: str) -> None:
        """Point the agent config in ``home`` at the memory server ``url``."""

    def install_guard(self, template_dir: Path) -> None:
        """Install the Bash guard into the agent template."""

    def copy_logins(self, home: Path) -> tuple[Path, ...]:
        """Copy the live agent logins into ``home`` and return the paths created."""

    def judge_argv(self, system_prompt: str) -> list[str]:
        """Return the argv, without the model, that runs the agent as a judge."""

    def judge_env(self, model: str, timeout_s: int) -> dict[str, str]:
        """Return the environment to run the judge ``model`` in."""
