"""Options for the `llm-prompts benchmark` command."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from llm_prompts import setup, size_report
from llm_prompts.benchmark import disk, paths, reuse
from llm_prompts.benchmark.agents import AGENTS, DEFAULT_MODELS
from llm_prompts.benchmark.agents.adapter import VariantBuildError
from llm_prompts.benchmark.cell import memory, variants
from llm_prompts.benchmark.cell.prepare import IsolationBreach
from llm_prompts.benchmark.cell.shared import remove_stale_roots
from llm_prompts.benchmark.fail_fast import SETUP_ERROR
from llm_prompts.benchmark.report import estimate as report_estimate
from llm_prompts.benchmark.report import pr as report_pr
from llm_prompts.benchmark.report.compare import (
    Report,
    compare,
    judge_reasons,
    size_changes,
    usage,
    verdict,
)
from llm_prompts.benchmark.report.render import render, to_json
from llm_prompts.benchmark.report.terminal import show
from llm_prompts.benchmark.runner.process import interrupt_on_termination
from llm_prompts.benchmark.runner.sandbox import SandboxMissing, require
from llm_prompts.benchmark.scenarios import loader as scenarios
from llm_prompts.benchmark.scenarios.checks.judge import JudgeMissing, require_judge
from llm_prompts.benchmark.scenarios.loader import ScenarioError
from llm_prompts.benchmark.scheduler import chain_sizes, label, plan, rescore
from llm_prompts.benchmark.scheduler import run as run_cells
from llm_prompts.benchmark.types import (
    DEFAULT_FAIL_FAST_AFTER,
    LEVEL_REPEATS,
    WORKTREE,
    Agent,
    Cell,
    Level,
    ResultRow,
    Scenario,
    Variant,
)

DEFAULT_JOBS = 4
EXIT_CODES = {"ok": 0, "regressed": 1, "all errored": 2, "aborted": 2}
EXIT_STOPPED = 2
WRITERS = {
    "report.md": render,
    "report.json": to_json,
    report_pr.FILE_NAME: report_pr.section,
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


def _at_least_one(name: str, value: int) -> int:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
    return value


@dataclass(frozen=True)
class RunOptions:
    a: str = "origin/main"
    b: str = WORKTREE
    level: Level = "light"
    agents: tuple[Agent, ...] = tuple(AGENTS)
    models: Mapping[Agent, str] = DEFAULT_MODELS
    repeats: int | None = None
    overlays: bool = True
    jobs: int = DEFAULT_JOBS
    scenarios: tuple[str, ...] = ()
    estimate_only: bool = False
    os_sandbox: bool = True
    judge: str = "auto"
    a_tools: Mapping[str, str] = field(default_factory=dict)
    b_tools: Mapping[str, str] = field(default_factory=dict)
    b_env: Mapping[str, str] = field(default_factory=dict)
    reuse: bool = True
    fail_fast: bool = False
    fail_fast_after: int = DEFAULT_FAIL_FAST_AFTER
    pr: str | None = None
    run_id: str | None = None
    apply: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> RunOptions:
        """Build options from parsed command-line arguments, using defaults for unset values."""
        defaults = cls()
        configured = setup.read_config().get("benchmark", {}).get("jobs", defaults.jobs)
        level = args.level or defaults.level
        if level not in LEVEL_REPEATS:
            raise ValueError(f"unknown level: {level}")
        models = dict(defaults.models)
        for entry in args.model or ():
            name, separator, model = entry.partition("=")
            if not separator:
                raise ValueError(f"model must be <agent>=<model id>: {entry}")
            models[_agent(name)] = model
        if (args.run or args.apply) and not args.pr:
            raise ValueError("--run and --apply need --pr")
        if args.run and args.estimate:
            raise ValueError("--run cannot be combined with --estimate")
        return cls(
            a=args.a or defaults.a,
            b=args.b or defaults.b,
            level=cast(Level, level),
            agents=tuple(dict.fromkeys(_agent(name) for name in args.agents.split(",")))
            if args.agents
            else defaults.agents,
            models=models,
            repeats=None
            if args.repeats is None
            else _at_least_one("repeats", args.repeats),
            overlays=args.overlays,
            jobs=_at_least_one("jobs", configured if args.jobs is None else args.jobs),
            scenarios=tuple(args.scenario or ()),
            estimate_only=args.estimate,
            os_sandbox=args.os_sandbox,
            judge=args.judge or defaults.judge,
            a_tools=_pairs("tool", args.a_tool),
            b_tools=_pairs("tool", args.b_tool),
            b_env=_pairs("env", args.b_env),
            reuse=args.reuse,
            fail_fast=args.fail_fast,
            fail_fast_after=_at_least_one(
                "fail-fast-after",
                defaults.fail_fast_after
                if args.fail_fast_after is None
                else args.fail_fast_after,
            ),
            pr=args.pr,
            run_id=args.run,
            apply=args.apply,
        )


def repeats_for(options: RunOptions) -> int:
    """Return the repeat count, from the options or the level default."""
    return options.repeats or LEVEL_REPEATS[options.level]


def _scenarios(options: RunOptions) -> list[Scenario]:
    return scenarios.load(options.level, options.agents, options.scenarios)


def estimate(
    options: RunOptions,
    scenarios: list[Scenario] | None = None,
    reused: Mapping[str, ResultRow] | None = None,
    cells: Sequence[Cell] = (),
) -> str:
    """Return a one-paragraph token and cost estimate for the chosen scenarios, leaving out the A cells in ``reused``."""
    result = report_estimate.estimate(
        _scenarios(options) if scenarios is None else scenarios,
        options.agents,
        repeats_for(options),
        Counter(
            (cell.scenario.id, cell.agent)
            for cell in cells
            if cell.id in (reused or {})
        ),
    )
    line = f"Estimated tokens: ~{result.total_tokens:,}"
    if result.context:
        line += f", peak context ~{result.context:,}"
    if result.cost_usd is not None:
        line += f", cost ~${result.cost_usd:.2f}"
    if options.reuse:
        line += f" (A: {result.reused_cells} of {result.a_cells} cells reused"
        if result.reused_cells and result.saved_usd is not None:
            line += f", ~${result.saved_usd:.2f} saved"
        line += ")"
    unknown = [f"No past runs: {name} ({agent})" for name, agent in result.unknown]
    return "\n".join([line, *unknown])


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
    return reused


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


def _attach(options: RunOptions, run_dir: Path) -> int:
    """Show, or with ``--apply`` write, the run's Benchmark section in the pull request ``--pr``."""
    repo = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    return report_pr.attach(cast("str", options.pr), run_dir, repo, options.apply)


def run(options: RunOptions) -> int:
    """Run the benchmark, write the report, and return the exit code."""
    with interrupt_on_termination():
        return _run(options)


@dataclass(frozen=True)
class _Plan:
    built: list[Variant]
    cells: list[Cell]
    selected: Mapping[str, ResultRow]


def _build_plan(options: RunOptions) -> _Plan:
    """Build side A, print the estimate and, unless only estimating, build side B and plan the cells."""
    scenarios = _scenarios(options)
    repeats = repeats_for(options)
    built = [
        variants.build(
            "a", options.a, options.agents, options.overlays, options.a_tools
        )
    ]
    a_cells = plan(built, options.agents, scenarios, repeats)
    selected = _reused(options, built[0], a_cells)
    print(estimate(options, scenarios, selected, a_cells))
    if options.estimate_only:
        return _Plan(built, [], selected)
    b = variants.build(
        "b", options.b, options.agents, options.overlays, options.b_tools
    )
    built.append(replace(b, env=options.b_env))
    cells = plan(built, options.agents, scenarios, repeats)
    b_cells = [cell for cell in cells if cell.variant.label == "b"]
    return _Plan(built, cells, selected | _reused(options, built[1], b_cells))


def _execute(options: RunOptions, chosen: _Plan, run_dir: Path) -> list[ResultRow]:
    """Re-score the reused cells, run the rest and return one row per cell."""
    cells = chosen.cells
    reused = rescore(
        [
            (cell, chosen.selected[cell.id])
            for cell in cells
            if cell.id in chosen.selected
        ],
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
    jobs = disk.fit(*disk.estimate(to_run), chain_sizes(to_run), options.jobs)
    if jobs < options.jobs:
        print(
            f"benchmark: using {jobs} jobs instead of {options.jobs}: not enough free disk for more",
            file=sys.stderr,
        )
    fresh = {
        row.cell_id: row
        for row in run_cells(
            to_run,
            jobs,
            options.models,
            run_dir,
            options.os_sandbox,
            options.judge,
            options.fail_fast_after if options.fail_fast else None,
        )
    }
    return [reused.get(cell.id) or fresh[cell.id] for cell in cells]


def _build_report(
    options: RunOptions, built: list[Variant], rows: list[ResultRow], run_id: str
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
        " ".join([options.b, *(f"{k}={v}" for k, v in options.b_env.items())]),
        options.level,
        options.agents,
        verdict(rows, deltas),
        tuple(deltas),
        size_changes(size_rows),
        note,
        usage(rows),
        judge_reasons(rows),
    )


def _publish(report: Report, rows: list[ResultRow], run_dir: Path) -> None:
    """Write the report files, print the console summary and say why a failed run failed."""
    for file, write in WRITERS.items():
        (run_dir / file).write_text(write(report))
    show(report)
    if report.verdict == "all errored":
        print("Every run errored", file=sys.stderr)
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
        if options.run_id:
            return _attach(options, paths.run_dir(options.run_id))
        if not options.estimate_only:
            require(options.os_sandbox)
            require_judge(options.judge)
            if missing := setup.missing_tools():
                variants.install_tools(missing)
        chosen = _build_plan(options)
        if options.estimate_only:
            return EXIT_CODES["ok"]
        if not chosen.cells:
            print("No cells planned for the chosen agents", file=sys.stderr)
            return EXIT_STOPPED
        run_dir = paths.run_dir(paths.new_run_id())
        run_dir.mkdir(parents=True)
        rows = _execute(options, chosen, run_dir)
        variants.prune(chosen.built)
        report = _build_report(options, chosen.built, rows, run_dir.name)
        _publish(report, rows, run_dir)
        if options.pr and _attach(options, run_dir):
            return EXIT_STOPPED
        return EXIT_CODES[report.verdict]
    except (
        disk.DiskShort,
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
