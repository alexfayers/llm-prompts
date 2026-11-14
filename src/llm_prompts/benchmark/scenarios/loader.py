"""Scenario TOML parsing, validation and loading."""

from __future__ import annotations

import dataclasses
import json
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast, get_args

from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.scenarios.checks import CHECKS
from llm_prompts.benchmark.types import (
    DEFAULT_GATE,
    Agent,
    CheckArg,
    CheckSpec,
    Gate,
    Level,
    MemoryEntity,
    Scenario,
)

DEFAULT_AGENTS: tuple[Agent, ...] = tuple(AGENTS)
DATA_DIR = Path(__file__).parent
DEFAULT_TIMEOUT_S = 300
TOP_KEYS = {field.name for field in dataclasses.fields(Scenario)} - {"checks"} | {
    "check"
}
GATE_KEYS = {field.name for field in dataclasses.fields(Gate)}
MEMORY_KEYS = {"name", "entityType", "observations", "relations", "status"}
RELATION_KEYS = {"target", "type"}
INHERITED_KEYS = ("workspace", "project", "memory", "agents", "setup", "delegation")
MISSING: Any = object()


class ScenarioError(Exception):
    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")


def _no_unknown_keys(path: Path, table: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ScenarioError(path, f"unknown key: {', '.join(unknown)}")


def _get(
    path: Path,
    table: Mapping[str, Any],
    key: str,
    kind: type | tuple[type, ...],
    default: Any = MISSING,
) -> Any:
    if key not in table:
        if default is MISSING:
            raise ScenarioError(path, f"missing key: {key}")
        return default
    value = table[key]
    if not isinstance(value, kind) or (kind is not bool and isinstance(value, bool)):
        raise ScenarioError(path, f"{key} has the wrong type")
    return value


def _strings(
    path: Path, table: Mapping[str, Any], key: str, default: Any
) -> tuple[str, ...]:
    items = _get(path, table, key, list, default)
    if not all(isinstance(item, str) for item in items):
        raise ScenarioError(path, f"{key} must be a list of strings")
    return tuple(items)


def _tables(path: Path, table: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    items = _get(path, table, key, list, [])
    if not all(isinstance(item, dict) for item in items):
        raise ScenarioError(path, f"{key} must be a list of tables")
    return cast(list[Mapping[str, Any]], items)


def _workspace(path: Path, name: str) -> Path:
    folder = path.parent / "fixtures" / name
    if name in ("", ".", "..") or "/" in name or "\\" in name:
        raise ScenarioError(path, f"workspace must be a folder name: {name}")
    if not folder.is_dir():
        raise ScenarioError(path, f"workspace folder does not exist: {folder}")
    return folder


def _gate(path: Path, table: Mapping[str, Any]) -> Gate:
    gate = _get(path, table, "gate", dict, {})
    _no_unknown_keys(path, gate, GATE_KEYS)
    return Gate(
        **{
            key: float(_get(path, gate, key, (int, float), getattr(DEFAULT_GATE, key)))
            for key in GATE_KEYS
        }
    )


def _memory(path: Path, table: Mapping[str, Any]) -> MemoryEntity:
    _no_unknown_keys(path, table, MEMORY_KEYS)
    relations = _tables(path, table, "relations")
    for relation in relations:
        _no_unknown_keys(path, relation, RELATION_KEYS)
    return MemoryEntity(
        name=_get(path, table, "name", str),
        entity_type=_get(path, table, "entityType", str),
        observations=_strings(path, table, "observations", MISSING),
        relations=tuple(
            (_get(path, relation, "target", str), _get(path, relation, "type", str))
            for relation in relations
        ),
        status=_get(path, table, "status", str, None),
    )


def _check(path: Path, table: Mapping[str, Any]) -> CheckSpec:
    kind = _get(path, table, "kind", str)
    if kind not in CHECKS:
        raise ScenarioError(path, f"unknown check kind: {kind}")
    args: dict[str, CheckArg] = {}
    for key, value in table.items():
        if key == "kind":
            continue
        if isinstance(value, list):
            args[key] = _strings(path, table, key, MISSING)
        elif isinstance(value, str | int):
            args[key] = value
        else:
            raise ScenarioError(path, f"check {kind} arg {key} has the wrong type")
    return CheckSpec(kind, args)


def _base(
    path: Path, data: Mapping[str, Any], parents: tuple[str, ...]
) -> Scenario | None:
    fresh = _get(path, data, "fresh", bool, False)
    if "base" not in data:
        if fresh:
            raise ScenarioError(path, "fresh needs a base")
        return None
    if own := [key for key in INHERITED_KEYS if key in data]:
        raise ScenarioError(path, f"a follow-up takes {', '.join(own)} from its base")
    name = _get(path, data, "base", str)
    base_path = path.parent / f"{name}.toml"
    if name != Path(name).name or not base_path.is_file():
        raise ScenarioError(path, f"base scenario does not exist: {name}")
    if name in parents or path.stem == name:
        raise ScenarioError(path, f"base {name} makes a cycle")
    base = parse(base_path, (*parents, path.stem))
    if base.base and not fresh:
        raise ScenarioError(path, f"base {name} is itself a follow-up")
    return base


def parse(path: Path, parents: tuple[str, ...] = ()) -> Scenario:
    """Parse and validate one scenario file."""
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ScenarioError(path, str(exc)) from exc
    _no_unknown_keys(path, data, TOP_KEYS)
    base = _base(path, data, parents)
    scenario_id = _get(path, data, "id", str)
    if scenario_id != path.stem:
        raise ScenarioError(
            path, f"id {scenario_id} does not match file name {path.name}"
        )
    level = _get(path, data, "level", str)
    if level not in get_args(Level):
        raise ScenarioError(path, f"unknown level: {level}")
    agents = (
        base.agents if base else _strings(path, data, "agents", list(DEFAULT_AGENTS))
    )
    if not agents or not set(agents) <= set(AGENTS):
        raise ScenarioError(
            path,
            f"agents must be a non-empty list of {' or '.join(AGENTS)}: {agents}",
        )
    delegation = (
        base.delegation if base else _get(path, data, "delegation", bool, False)
    )
    delegating = [name for name, agent in AGENTS.items() if agent.delegation]
    if delegation and not set(agents) <= set(delegating):
        raise ScenarioError(path, f"delegation needs agents = {json.dumps(delegating)}")
    timeout_s = _get(path, data, "timeout_s", int, DEFAULT_TIMEOUT_S)
    if timeout_s < 1:
        raise ScenarioError(path, f"timeout_s must be at least 1: {timeout_s}")
    checks = _tables(path, data, "check")
    if not checks:
        raise ScenarioError(path, "at least one [[check]] is required")
    return Scenario(
        id=scenario_id,
        level=cast(Level, level),
        agents=cast(tuple[Agent, ...], agents),
        workspace=base.workspace
        if base
        else _workspace(path, _get(path, data, "workspace", str)),
        project=base.project if base else _get(path, data, "project", str),
        prompt=_get(path, data, "prompt", str),
        timeout_s=timeout_s,
        gate=_gate(path, data),
        memory=base.memory
        if base
        else tuple(_memory(path, entity) for entity in _tables(path, data, "memory")),
        checks=tuple(_check(path, check) for check in checks),
        base=base,
        fresh=_get(path, data, "fresh", bool, False),
        headline=_get(path, data, "headline", bool, False),
        setup=base.setup if base else _strings(path, data, "setup", []),
        delegation=delegation,
    )


def load(
    level: Level, agents: Sequence[Agent], ids: Sequence[str] = ()
) -> list[Scenario]:
    """Load the scenarios up to ``level`` that run on ``agents``, optionally only the given ids."""
    levels = get_args(Level)
    allowed = levels[: levels.index(level) + 1]
    scenarios = sorted(
        (
            scenario
            for scenario in map(parse, DATA_DIR.glob("*.toml"))
            if scenario.level in allowed and set(scenario.agents) & set(agents)
        ),
        key=lambda scenario: scenario.id,
    )
    if ids:
        available = {scenario.id for scenario in scenarios}
        for scenario_id in ids:
            if scenario_id not in available:
                raise ScenarioError(
                    DATA_DIR,
                    f"scenario {scenario_id!r} not found at level {level} for agents"
                    f" {', '.join(agents)}",
                )
        scenarios = [scenario for scenario in scenarios if scenario.id in ids]
    chosen = {scenario.id: scenario for scenario in scenarios}
    for scenario in scenarios:
        ancestor = scenario.base
        while ancestor:
            chosen.setdefault(ancestor.id, ancestor)
            ancestor = ancestor.base
    return sorted(chosen.values(), key=lambda scenario: scenario.id)
