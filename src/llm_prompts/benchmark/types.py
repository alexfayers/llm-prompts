"""Shared frozen shapes used across the benchmark."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

Level = Literal["light", "medium", "heavy"]
Agent = Literal["claude", "pi"]

DEFAULT_FAIL_FAST_AFTER = 3
WORKTREE = ":worktree"
SCHEMA_VERSION = 8

CheckArg = str | int | bool | tuple[str, ...]
JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True)
class Gate:
    max_pass_drop: float
    max_context_rise: float
    max_cost_rise: float
    max_time_rise: float


DEFAULT_GATE = Gate(
    max_pass_drop=0.34, max_context_rise=0.25, max_cost_rise=0.5, max_time_rise=0.5
)


@dataclass(frozen=True)
class MemoryEntity:
    name: str
    entity_type: str
    observations: tuple[str, ...]
    relations: tuple[tuple[str, str], ...] = ()
    status: str | None = None


@dataclass(frozen=True)
class CheckSpec:
    kind: str
    args: Mapping[str, CheckArg]


@dataclass(frozen=True)
class Scenario:
    id: str
    level: Level
    agents: tuple[Agent, ...]
    workspace: Path
    project: str
    prompt: str
    timeout_s: int
    gate: Gate
    memory: tuple[MemoryEntity, ...]
    checks: tuple[CheckSpec, ...]
    base: Scenario | None = None
    fresh: bool = False
    headline: bool = False
    setup: tuple[str, ...] = ()
    delegation: bool = False

    @property
    def ask(self) -> str:
        """Return the prompt that gave the task: the base's for a conversation follow-up."""
        return self.base.ask if self.base and not self.fresh else self.prompt

    @property
    def root(self) -> Scenario:
        """Return the scenario at the top of the base chain."""
        return self.base.root if self.base else self


@dataclass(frozen=True)
class Session:
    id: str
    fork: str | None = None


@dataclass(frozen=True)
class Variant:
    label: Literal["a", "b"]
    ref: str
    key: str
    src: Path
    venv: Path
    templates: Mapping[Agent, Path]
    build: Mapping[Agent, str] | None = None
    env: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True)
class Cell:
    variant: Variant
    agent: Agent
    scenario: Scenario
    repeat: int

    @property
    def id(self) -> str:
        """Return a label that identifies the cell."""
        return self._id_of(self.scenario)

    @property
    def base_id(self) -> str | None:
        """Return the id of the cell this one follows up, if any."""
        return self._id_of(self.scenario.base) if self.scenario.base else None

    def _id_of(self, scenario: Scenario) -> str:
        return f"{self.variant.label}-{self.agent}-{scenario.id}-{self.repeat}"


@dataclass(frozen=True)
class MemoryHandle:
    url: str
    port: int
    db: Path

    def env(self) -> dict[str, str]:
        """Return the environment variables that point a process at this server."""
        return {
            "MCP_MEMORY_PORT": str(self.port),
            "MCP_MEMORY_URL": self.url,
            "MCP_MEMORY_DB_PATH": str(self.db),
        }


@dataclass(frozen=True)
class PreparedCell:
    cell: Cell
    root: Path
    home: Path
    workspace: Path
    env: Mapping[str, str]
    memory: MemoryHandle
    seeded: tuple[MemoryEntity, ...]


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Mapping[str, JsonValue]
    ok: bool
    at: float = 0.0
    error: str = ""
    output: str = ""
    subagent: bool = False

    @property
    def text(self) -> str:
        """Return the result text of the call: its error or its output."""
        return self.error or self.output


@dataclass(frozen=True)
class Tokens:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def total(self) -> int:
        """Return the sum of all token counts."""
        return self.input + self.output + self.cache_read + self.cache_write


@dataclass(frozen=True, kw_only=True)
class Trace:
    tool_calls: tuple[ToolCall, ...] = ()
    final_text: str = ""
    tokens: Tokens = Tokens()
    wall_s: float = 0.0
    model: str = ""
    exit_code: int = 0
    injected_context: str = ""
    error: str = ""
    context: int = 0
    start_context: int = 0
    cost_usd: float | None = None
    turns: int = 0


@dataclass(frozen=True)
class CheckOutcome:
    kind: str
    passed: bool
    detail: str
    tokens: int = 0


@dataclass(frozen=True)
class MemoryMetrics:
    memory_calls: int = 0
    read_before_first_edit: bool = False
    entities_added: int = 0
    observations_added: int = 0
    relations_added: int = 0
    invalid_names: int = 0


def _pick[T](kind: type[T], raw: Mapping[str, Any]) -> T:
    names = {f.name for f in fields(kind)}  # type: ignore[arg-type]
    return kind(**{k: v for k, v in raw.items() if k in names})


@dataclass(frozen=True, kw_only=True)
class ResultRow:
    """One line of ``results.jsonl``: the outcome of a cell."""

    schema: int = SCHEMA_VERSION
    run_id: str = ""
    reuse_key: str | None = None
    reuse_parts: Mapping[str, str] | None = None
    cell_id: str = ""
    variant: str
    ref: str = ""
    commit: str = ""
    agent: Agent
    model: str = ""
    scenario: str
    level: str = ""
    repeat: int = 0
    passed: bool = False
    gate: Gate = DEFAULT_GATE
    checks: tuple[CheckOutcome, ...] = ()
    tokens: Tokens = Tokens()
    judge_tokens: int = 0
    context: int = 0
    start_context: int = 0
    cost_usd: float | None = None
    turns: int = 0
    tool_calls: int = 0
    failed_test_runs: int = 0
    wall_s: float = 0.0
    memory: MemoryMetrics = MemoryMetrics()
    base: str | None = None
    follow_up_of: str | None = None
    fresh: bool = False
    headline: bool = False
    isolated: bool = True
    fork_gap_s: float | None = None
    error: str | None = None
    startup_error: bool = False
    retries: int = 0
    retry_cost_usd: float | None = None
    skipped: str | None = None
    reused_from: str | None = None

    def to_json(self) -> dict[str, JsonValue]:
        """Return the row as a JSON object, leaving out ``reused_from`` unless the row was reused."""
        raw: dict[str, JsonValue] = asdict(self)
        if self.reused_from is None:
            del raw["reused_from"]
        return raw

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> ResultRow:
        """Return the row of a JSON object, with defaults for what an older row lacks."""
        data = {f.name: raw[f.name] for f in fields(cls) if f.name in raw}
        for name, kind in (
            ("gate", Gate),
            ("tokens", Tokens),
            ("memory", MemoryMetrics),
        ):
            if name in data:
                data[name] = _pick(kind, {**asdict(getattr(cls, name)), **data[name]})
        if "checks" in data:
            data["checks"] = tuple(_pick(CheckOutcome, c) for c in data["checks"])
        return cls(**data)
