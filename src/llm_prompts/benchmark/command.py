"""Options for the `llm-prompts benchmark` command."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast, get_args

from llm_prompts import setup, size_report
from llm_prompts.attic.pinned import PINNED_RULES
from llm_prompts.benchmark import paths, reuse
from llm_prompts.benchmark.agents import AGENTS, DEFAULT_MODELS
from llm_prompts.benchmark.agents.adapter import VariantBuildError
from llm_prompts.benchmark.agents.pi import FEATURES
from llm_prompts.benchmark.cell import memory, variants
from llm_prompts.benchmark.cell.prepare import IsolationBreach
from llm_prompts.benchmark.cell.shared import remove_stale_roots
from llm_prompts.benchmark.fail_fast import SETUP_ERROR, is_setup_error
from llm_prompts.benchmark.report.compare import (
    MIN_GATED_RUNS,
    Report,
    ablation_verdict,
    compare,
    judge_reasons,
    needs_more_runs,
    size_changes,
    usage,
    verdict,
)
from llm_prompts.benchmark.report.render import GATE_TEXT, render, to_json
from llm_prompts.benchmark.report.terminal import show
from llm_prompts.benchmark.runner.process import interrupt_on_termination
from llm_prompts.benchmark.runner.sandbox import SandboxMissing, require
from llm_prompts.benchmark.scenarios import loader as scenarios
from llm_prompts.benchmark.scenarios.checks.judge import JudgeMissing, require_judge
from llm_prompts.benchmark.scenarios.loader import ScenarioError
from llm_prompts.benchmark.scheduler import label, plan, rescore
from llm_prompts.benchmark.scheduler import run as run_cells
from llm_prompts.benchmark.types import (
    DEFAULT_FAIL_FAST_AFTER,
    WORKTREE,
    Agent,
    Cell,
    Level,
    ResultRow,
    Scenario,
    Variant,
)

DEFAULT_JOBS = 4
EXIT_CODES = {"ok": 0, "regressed": 1, "all errored": 2, "incomplete": 2, "aborted": 2}
EXIT_STOPPED = 2
WRITERS = {
    "report.md": render,
    "report.json": to_json,
}
BUILD_HINT = (
    "the A ref, a tool's origin/main, an overlay or the rendered agent files changed"
)


def _agent(name: str) -> Agent:
    if name not in AGENTS:
        raise ValueError(f"unknown agent: {name}")
    return cast(Agent, name)


def _pairs(kind: str, entries: list[str] | None) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for entry in entries or ():
        name, separator, value = entry.partition("=")
        if not (separator and name and value):
            raise ValueError(f"{kind} must be <name>=<value>: {entry}")
        pairs[name] = value
    return pairs


def at_least_one(name: str, value: int) -> int:
    """Return ``value``, or raise ValueError naming ``name`` when it is not an int of at least 1."""
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
    return value


def _unpinned_rules(names: Sequence[str] | None) -> tuple[str, ...]:
    if pinned := PINNED_RULES.intersection(names or ()):
        raise ValueError(f"{', '.join(sorted(pinned))}: pinned, never demoted")
    return tuple(dict.fromkeys(names or ()))


def _features(names: Sequence[str] | None) -> tuple[str, ...]:
    if unknown := set(names or ()) - set(FEATURES):
        raise ValueError(
            f"unknown feature: {', '.join(sorted(unknown))} (one of {', '.join(FEATURES)})"
        )
    return tuple(dict.fromkeys(names or ()))


@dataclass(frozen=True)
class RunOptions:
    a: str = "origin/main"
    b: str = WORKTREE
    level: Level = "light"
    agents: tuple[Agent, ...] = tuple(AGENTS)
    models: Mapping[Agent, str] = field(default_factory=lambda: DEFAULT_MODELS)
    repeats: int | None = None
    max_repeats: int = MIN_GATED_RUNS
    overlays: tuple[str, ...] = ()
    jobs: int = DEFAULT_JOBS
    scenarios: tuple[str, ...] = ()
    os_sandbox: bool = True
    judge: str = "auto"
    a_tools: Mapping[str, str] = field(default_factory=dict)
    b_tools: Mapping[str, str] = field(default_factory=dict)
    b_env: Mapping[str, str] = field(default_factory=dict)
    b_drop: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    reuse: bool = True
    fail_fast: bool = False
    fail_fast_after: int = DEFAULT_FAIL_FAST_AFTER

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> RunOptions:
        """Build options from parsed command-line arguments, using defaults for unset values."""
        defaults = cls()
        config = setup.read_config()
        configured = config.get("benchmark", {}).get("jobs", defaults.jobs)
        level = args.level or defaults.level
        if level not in get_args(Level):
            raise ValueError(f"unknown level: {level}")
        models: dict[Agent, str] = {}
        for entry in args.model or ():
            name, separator, model = entry.partition("=")
            if not separator:
                raise ValueError(f"model must be <agent>=<model id>: {entry}")
            models[_agent(name)] = model
        features = _features(args.feature)
        chosen = (
            tuple(dict.fromkeys(_agent(name) for name in args.agents.split(",")))
            if args.agents
            else ("pi",)
            if features
            else defaults.agents
        )
        if features and chosen != ("pi",):
            raise ValueError("--feature measures pi features, use --agents pi")
        if features and args.b_tool:
            raise ValueError(
                "--feature builds both sides from one tool config, use --a-tool"
            )
        for agent in chosen:
            if agent not in models:
                models[agent] = defaults.models[agent]
        available = variants.overlay_names(config)
        if unknown := set(args.overlay or ()) - set(available):
            raise ValueError(f"unknown overlay: {', '.join(sorted(unknown))}")
        return cls(
            a=args.a or defaults.a,
            b=args.b or defaults.b,
            level=cast(Level, level),
            agents=chosen,
            models=models,
            repeats=None
            if args.repeats is None
            else at_least_one("repeats", args.repeats),
            max_repeats=defaults.max_repeats
            if args.max_repeats is None
            else at_least_one("max-repeats", args.max_repeats),
            overlays=available
            if args.overlays
            else tuple(dict.fromkeys(args.overlay or ())),
            jobs=at_least_one("jobs", configured if args.jobs is None else args.jobs),
            scenarios=tuple(args.scenario or ()),
            os_sandbox=args.os_sandbox,
            judge=args.judge or defaults.judge,
            a_tools=_pairs("tool", args.a_tool),
            b_tools=_pairs("tool", args.b_tool),
            b_env=_pairs("env", args.b_env),
            b_drop=_unpinned_rules(args.b_drop),
            features=features,
            reuse=args.reuse,
            fail_fast=args.fail_fast,
            fail_fast_after=at_least_one(
                "fail-fast-after",
                defaults.fail_fast_after
                if args.fail_fast_after is None
                else args.fail_fast_after,
            ),
        )


def _scenarios(options: RunOptions) -> list[Scenario]:
    return scenarios.load(options.level, options.agents, options.scenarios)


def _reused(
    options: RunOptions, variant: Variant, cells: list[Cell]
) -> dict[str, ResultRow]:
    if not options.reuse:
        return {}
    if variant.build is None:
        print(
            f"benchmark: {variant.label.upper()} runs are not reused, because {variant.ref} has a tool source that is not pinned."
            " Use a local checkout or <source>@<commit sha>.",
            file=sys.stderr,
        )
        return {}
    prior = reuse.load()
    reused = reuse.select(
        cells,
        prior,
        lambda cell: reuse.key(cell, options.models[cell.agent], options.os_sandbox),
    )
    _announce(options, cells, reused, prior)
    return reused


def _announce(
    options: RunOptions,
    cells: Sequence[Cell],
    reused: Mapping[str, ResultRow],
    prior: Sequence[ResultRow],
) -> None:
    for cell in cells:
        if row := reused.get(cell.id):
            print(
                f"benchmark: reused {label(cell)} from {reuse.origin(row)}",
                file=sys.stderr,
            )
        else:
            current = reuse.parts(cell, options.models[cell.agent], options.os_sandbox)
            print(
                f"benchmark: not reused {label(cell)}: {_difference(cell, current, prior)}",
                file=sys.stderr,
            )


def _difference(
    cell: Cell, current: Mapping[str, str] | None, prior: Sequence[ResultRow]
) -> str:
    closest = reuse.closest_differences(cell, current or {}, prior)
    if closest is None:
        return "no earlier run to compare"
    run_id, names = closest
    if not names:
        return f"{run_id} has the same inputs but errored or lost its saved outputs"
    verb = "differs" if len(names) == 1 else "differ"
    line = f"{' and '.join(names)} {verb} from {run_id}"
    if "build" in names:
        line += f" ({BUILD_HINT})"
    return line


def run(options: RunOptions) -> int:
    """Run the benchmark, write the report, and return the exit code."""
    with interrupt_on_termination():
        return _run(options)


@dataclass(frozen=True)
class _Plan:
    built: list[Variant]
    scenarios: list[Scenario]
    cells: list[Cell]
    selected: Mapping[str, ResultRow]


def _build_plan(options: RunOptions) -> _Plan:
    """Build both sides and plan the first cells."""
    scenarios = _scenarios(options)
    built = [
        replace(
            variants.build(
                "a", options.a, options.agents, options.overlays, options.a_tools
            ),
            features=dict.fromkeys(options.features, False),
        )
    ]
    a_cells = plan(built, options.agents, scenarios, range(options.repeats or 1))
    selected = _reused(options, built[0], a_cells)
    b = variants.build(
        "b",
        options.b,
        options.agents,
        options.overlays,
        options.a_tools if options.features else options.b_tools,
        drop=options.b_drop,
        origin_tools=bool(options.features) or None,
    )
    built.append(
        replace(b, env=options.b_env, features=dict.fromkeys(options.features, True))
    )
    cells = plan(built, options.agents, scenarios, range(options.repeats or 1))
    b_cells = [cell for cell in cells if cell.variant.label == "b"]
    return _Plan(
        built, scenarios, cells, selected | _reused(options, built[1], b_cells)
    )


def _run_round(
    options: RunOptions,
    cells: list[Cell],
    selected: Mapping[str, ResultRow],
    run_dir: Path,
) -> list[ResultRow]:
    """Re-score the reused cells, run the rest and return one row per cell."""
    reused = rescore(
        [(cell, selected[cell.id]) for cell in cells if cell.id in selected],
        options.jobs,
        options.models,
        run_dir,
        options.os_sandbox,
        options.judge,
    )
    with (run_dir / "results.jsonl").open("a") as handle:
        handle.writelines(json.dumps(row.to_json()) + "\n" for row in reused.values())
    remove_stale_roots()
    to_run = [cell for cell in cells if cell.id not in reused]
    fresh = {
        row.cell_id: row
        for row in run_cells(
            to_run,
            options.jobs,
            options.models,
            run_dir,
            options.os_sandbox,
            options.judge,
            options.fail_fast_after if options.fail_fast else None,
        )
    }
    return [reused.get(cell.id) or fresh[cell.id] for cell in cells]


def _next_cells(
    options: RunOptions, chosen: _Plan, rows: list[ResultRow], repeat: int
) -> list[Cell]:
    """Return the cells of repeat ``repeat`` for the scenarios and agents whose runs so far still differ between A and B."""
    if options.fail_fast and any(
        (row.skipped or "").startswith(SETUP_ERROR)
        or (row.error and is_setup_error(row.error))
        for row in rows
    ):
        return []
    roots = {scenario.id: scenario.root.id for scenario in chosen.scenarios}
    open_ = {
        (roots[delta.scenario], delta.agent)
        for delta in compare(rows)
        if needs_more_runs(delta)
    }
    return [
        cell
        for cell in plan(chosen.built, options.agents, chosen.scenarios, [repeat])
        if (cell.scenario.root.id, cell.agent) in open_
    ]


def _execute(options: RunOptions, chosen: _Plan, run_dir: Path) -> list[ResultRow]:
    """Run the first cells, then without ``--repeats`` one more round for each scenario that A and B still differ on, up to ``max_repeats``."""
    rows = _run_round(options, chosen.cells, chosen.selected, run_dir)
    for repeat in range(1, 1 if options.repeats else options.max_repeats):
        cells = _next_cells(options, chosen, rows, repeat)
        if not cells:
            break
        selected: dict[str, ResultRow] = {}
        for variant in chosen.built:
            side = [cell for cell in cells if cell.variant.label == variant.label]
            selected |= _reused(options, variant, side)
        rows += _run_round(options, cells, selected, run_dir)
    return rows


def _build_report(
    options: RunOptions,
    built: list[Variant],
    planned: Sequence[Scenario],
    rows: list[ResultRow],
    run_id: str,
) -> Report:
    deltas = compare(rows)
    base, head = (variant.src / variants.PROMPTS for variant in built)
    note = size_report.missing_note(base, head)
    size_rows = (
        []
        if note
        else size_report.measure(
            base, head, *(variants.overlay_prompts(variant) for variant in built)
        )
    )
    return Report(
        run_id,
        options.a,
        options.b,
        options.level,
        options.agents,
        verdict(rows, deltas),
        tuple(deltas),
        size_changes(size_rows),
        note,
        usage(rows),
        judge_reasons(rows),
        options.b_env,
        options.b_drop,
        options.features,
        ablation_verdict(
            rows,
            deltas,
            options.b_drop,
            {scenario.id: scenario.covers for scenario in planned},
        )
        if options.b_drop
        else None,
    )


def _publish(report: Report, rows: list[ResultRow], run_dir: Path) -> None:
    """Write the report files, print the console summary and say why a failed run failed."""
    for file, write in WRITERS.items():
        (run_dir / file).write_text(write(report))
    show(report)
    if report.verdict == "all errored":
        print("Every run errored", file=sys.stderr)
    if report.verdict == "incomplete":
        print(GATE_TEXT["incomplete"], file=sys.stderr)
    if report.verdict == "aborted":
        print(
            next(
                skipped
                for row in rows
                if (skipped := row.skipped) and skipped.startswith(SETUP_ERROR)
            ),
            file=sys.stderr,
        )
    print(f"Report: {run_dir / 'report.md'}")
    print(f"JSON: {run_dir / 'report.json'}")


def _run(options: RunOptions) -> int:
    try:
        require(options.os_sandbox)
        require_judge(options.judge)
        if missing := setup.missing_tools():
            variants.install_tools(missing)
        chosen = _build_plan(options)
        if not chosen.cells:
            print("No cells planned for the chosen agents", file=sys.stderr)
            return EXIT_STOPPED
        run_dir = paths.run_dir(paths.new_run_id())
        run_dir.mkdir(parents=True)
        rows = _execute(options, chosen, run_dir)
        variants.prune(chosen.built)
        report = _build_report(
            options, chosen.built, chosen.scenarios, rows, run_dir.name
        )
        _publish(report, rows, run_dir)
        return EXIT_CODES[report.verdict]
    except (
        SandboxMissing,
        JudgeMissing,
        ScenarioError,
        VariantBuildError,
        IsolationBreach,
        memory.MemoryStartError,
        subprocess.CalledProcessError,
    ) as exc:
        print(exc, file=sys.stderr)
        return EXIT_STOPPED
