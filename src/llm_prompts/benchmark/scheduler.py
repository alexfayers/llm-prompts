"""Order benchmark cells, run them and write their results."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import NamedTuple, cast

from llm_prompts.benchmark import reuse, saved, transient
from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.cell import memory
from llm_prompts.benchmark.cell.audit import audit_trace, live_memory
from llm_prompts.benchmark.cell.env import isolated_env
from llm_prompts.benchmark.cell.memory import metrics
from llm_prompts.benchmark.cell.prepare import prepare, prepare_fork, snapshot
from llm_prompts.benchmark.cell.shared import SharedStores
from llm_prompts.benchmark.fail_fast import (
    BASE_FAILED,
    BASE_SKIPPED,
    ISOLATION_BREACH,
    TIMEOUT,
    FailFast,
)
from llm_prompts.benchmark.live_view import LiveView
from llm_prompts.benchmark.paths import cell_mount
from llm_prompts.benchmark.runner import process
from llm_prompts.benchmark.runner.process import reset_stop
from llm_prompts.benchmark.runner.sandbox import SandboxPolicy, remaps_paths
from llm_prompts.benchmark.scenarios.checks import evaluate, failed_test_runs
from llm_prompts.benchmark.scenarios.checks.context import CheckContext
from llm_prompts.benchmark.transient import NO_RETRIES, Retries
from llm_prompts.benchmark.types import (
    Agent,
    Cell,
    CheckOutcome,
    MemoryEntity,
    MemoryMetrics,
    PreparedCell,
    ResultRow,
    Scenario,
    Session,
    Trace,
    Variant,
)

BASE_SESSION = "bench-base"
MAX_REASON_CHARS = 200
JUDGEMENT_FILE = "judge-{}.txt"
JUDGEMENT_GLOB = "judge-*.txt"
TERMINAL_ESCAPE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]"
)
HOOK_FAILURE = re.compile(r"^\S+ hook \[.*\] failed: ")


class Scored(NamedTuple):
    trace: Trace
    outcomes: list[CheckOutcome]
    metrics: MemoryMetrics
    memory_before: tuple[MemoryEntity, ...]
    memory_after: tuple[MemoryEntity, ...]


def _score(
    prepared: PreparedCell,
    trace: Trace,
    settings: Settings,
    base_trace: Trace | None = None,
) -> Scored:
    cell = prepared.cell
    before = prepared.seeded
    after = memory.read_entities(prepared.memory)
    merged = replace(
        trace,
        tool_calls=tuple(
            sorted(
                [*memory.read_tool_calls(prepared.memory), *trace.tool_calls],
                key=lambda call: call.at,
            )
        ),
    )
    context = CheckContext(
        merged,
        prepared.workspace,
        before,
        after,
        settings.judge,
        base_trace,
        cell.scenario.ask,
        cell.variant.venv,
        settings.policy(prepared),
        prepared.env,
    )
    return Scored(
        merged,
        evaluate(cell.scenario.checks, context),
        metrics(merged, before, after),
        before,
        after,
    )


def _error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return TIMEOUT
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


def _reason(prepared: PreparedCell, trace: Trace) -> str:
    if trace.error:
        return trace.error[:MAX_REASON_CHARS]
    log = prepared.root / "agent.log"
    text = TERMINAL_ESCAPE.sub("", log.read_text()) if log.exists() else ""
    stripped = (line.strip() for line in text.splitlines())
    plain = [line for line in stripped if line and not line.startswith("{")]
    other = [line for line in plain if not HOOK_FAILURE.match(line)]
    final = trace.final_text.strip().splitlines()
    return (other or plain or final or [""])[-1][:MAX_REASON_CHARS]


def _row(
    cell: Cell,
    settings: Settings,
    error: str | None,
    scored: Scored | None,
    isolated: bool = True,
    fork_gap_s: float | None = None,
    retries: Retries = NO_RETRIES,
) -> ResultRow:
    trace, outcomes, memory = scored[:3] if scored else (Trace(), [], MemoryMetrics())
    model = settings.models[cell.agent]
    return ResultRow(
        run_id=settings.run_dir.name,
        reuse_key=reuse.key(cell, model, settings.os_sandbox),
        reuse_parts=reuse.parts(cell, model, settings.os_sandbox),
        cell_id=cell.id,
        variant=cell.variant.label,
        ref=cell.variant.ref,
        commit=cell.variant.key,
        agent=cell.agent,
        model=trace.model,
        scenario=cell.scenario.id,
        level=cell.scenario.level,
        repeat=cell.repeat,
        passed=error is None and all(outcome.passed for outcome in outcomes),
        gate=cell.scenario.gate,
        checks=tuple(outcomes),
        tokens=trace.tokens,
        judge_tokens=sum(outcome.tokens for outcome in outcomes),
        context=trace.context,
        start_context=trace.start_context,
        cost_usd=trace.cost_usd,
        turns=trace.turns,
        tool_calls=len(trace.tool_calls),
        failed_test_runs=failed_test_runs(trace),
        wall_s=trace.wall_s,
        memory=memory,
        base=cell.base_id,
        follow_up_of=cell.scenario.base.id if cell.scenario.base else None,
        fresh=cell.scenario.fresh,
        headline=cell.scenario.headline,
        isolated=isolated,
        fork_gap_s=fork_gap_s,
        error=error,
        startup_error=transient.is_startup_error(error),
        retries=retries.count,
        retry_cost_usd=retries.cost_usd,
    )


def _skip_row(cell: Cell, settings: Settings, reason: str) -> ResultRow:
    return replace(
        _row(cell, settings, None, None),
        passed=False,
        reuse_key=None,
        reuse_parts=None,
        skipped=reason,
    )


def label(cell: Cell) -> str:
    return f"{cell.scenario.id} {cell.agent} {cell.variant.ref} #{cell.repeat + 1}"


def _keep_logs(prepared: PreparedCell, destination: Path) -> None:
    for source in (
        prepared.root / "agent.log",
        prepared.home / "memory.log",
        prepared.home / ".cline-hooks" / "cline-hooks.log",
    ):
        if source.exists():
            shutil.copy2(source, destination / source.name)


@dataclass(frozen=True)
class Settings:
    models: Mapping[Agent, str]
    run_dir: Path
    os_sandbox: bool
    judge: str
    seen: Path | None
    stores: SharedStores = field(default_factory=SharedStores)
    agent_slots: threading.Semaphore = field(
        default_factory=lambda: threading.Semaphore(1)
    )
    stagger: transient.Stagger = field(
        default_factory=lambda: transient.Stagger(transient.STAGGER_S)
    )

    def policy(self, prepared: PreparedCell) -> SandboxPolicy | None:
        """Return the OS sandbox the cell's agent and checks run in, or None when disabled."""
        if not self.os_sandbox:
            return None
        return SandboxPolicy(
            (prepared.root,),
            (live_memory()[1],),
            (prepared.root, self.seen) if self.seen else None,
            self.stores.roots(),
        )


Record = Callable[[Cell, ResultRow], None]
AfterBase = Callable[[PreparedCell, str | None, float, float, Trace | None], None]


def _execute(
    prepared: PreparedCell,
    cell: Cell,
    settings: Settings,
    on_tool: Callable[[str], None],
    on_reply: Callable[[], None] | None,
    session: Session | None,
    cost_offset: float = 0.0,
    base_trace: Trace | None = None,
) -> tuple[Scored | None, str | None]:
    scored: Scored | None = None
    error: str | None = None
    try:
        with settings.agent_slots:
            settings.stagger.wait()
            trace = process.execute(
                prepared,
                cell.scenario,
                settings.models[cell.agent],
                settings.policy(prepared),
                on_tool,
                on_reply,
                session,
            )
        if trace.cost_usd is not None:
            trace = replace(trace, cost_usd=trace.cost_usd - cost_offset)
        scored = _score(prepared, trace, settings, base_trace)
        if trace.exit_code:
            reason = _reason(prepared, trace)
            error = f"agent exit {trace.exit_code}"
            if reason:
                error = f"{error}: {reason}"
            if transient.is_transient(trace, reason):
                error = transient.STARTUP_ERROR + error
        if hits := audit_trace(scored.trace):
            error = ISOLATION_BREACH + ", ".join(
                f"{hit.path}: {hit.marker}" for hit in hits
            )
    except Exception as exc:
        error = _error(exc)
    return scored, error


def _save_judgements(
    destination: Path, cell: Cell, outcomes: list[CheckOutcome]
) -> None:
    for stale in destination.glob(JUDGEMENT_GLOB):
        stale.unlink()
    judged = [
        (spec, outcome)
        for spec, outcome in zip(cell.scenario.checks, outcomes, strict=True)
        if outcome.kind == "judge"
    ]
    for number, (spec, outcome) in enumerate(judged, 1):
        (destination / JUDGEMENT_FILE.format(number)).write_text(
            f"Rubric:\n{spec.args.get('rubric')}\n\n{outcome.detail}\n"
        )


def _save(
    prepared: PreparedCell, cell: Cell, settings: Settings, scored: Scored | None
) -> None:
    destination = settings.run_dir / "cells" / cell.id
    destination.mkdir(parents=True, exist_ok=True)
    _keep_logs(prepared, destination)
    if scored:
        saved.write(
            destination,
            prepared.workspace,
            scored.trace,
            scored.memory_before,
            scored.memory_after,
        )
        _save_judgements(destination, cell, scored.outcomes)


def _run_cell(
    cell: Cell,
    settings: Settings,
    on_tool: Callable[[str], None],
    on_reply: Callable[[], None] | None,
    session: Session | None,
    record: Record,
    after: AfterBase | None,
) -> None:
    retries = NO_RETRIES
    while True:
        with prepare(cell, settings.seen, settings.stores) as prepared:
            scored, error = _execute(
                prepared, cell, settings, on_tool, on_reply, session
            )
            if not transient.is_startup_error(error) or retries.exhausted:
                _save(prepared, cell, settings, scored)
                ended = time.monotonic()
                record(cell, _row(cell, settings, error, scored, retries=retries))
                if after:
                    cost = scored.trace.cost_usd if scored else None
                    offset = cost or 0.0 if AGENTS[cell.agent].cumulative_cost else 0.0
                    after(
                        prepared, error, ended, offset, scored.trace if scored else None
                    )
                return
        retries = retries.after(scored.trace if scored else None)
        process.pause(transient.backoff())


def _follow_up_session(cell: Cell) -> Session | None:
    if cell.scenario.fresh:
        return None
    return Session(f"bench-{cell.scenario.id}", BASE_SESSION)


def _fork_row(
    cell: Cell,
    settings: Settings,
    error: str | None,
    scored: Scored | None,
    gap: float | None = None,
    retries: Retries = NO_RETRIES,
) -> ResultRow:
    return _row(
        cell,
        settings,
        error,
        scored,
        isolated=settings.seen is not None,
        fork_gap_s=gap,
        retries=retries,
    )


def _run_follow_up(
    open_prepared: Callable[[], AbstractContextManager[PreparedCell]],
    cell: Cell,
    settings: Settings,
    on_tool: Callable[[str], None],
    ended: float,
    cost_offset: float,
    base_trace: Trace | None,
    record: Record,
    after: AfterBase | None,
) -> ResultRow:
    with open_prepared() as prepared:
        gap = time.monotonic() - ended
        retries = NO_RETRIES
        while True:
            scored, error = _execute(
                prepared,
                cell,
                settings,
                on_tool,
                None,
                _follow_up_session(cell),
                cost_offset,
                base_trace,
            )
            if not transient.is_startup_error(error) or retries.exhausted:
                break
            retries = retries.after(scored.trace if scored else None)
            process.pause(transient.backoff())
            memory.clear_tool_calls(prepared.memory)
        _save(prepared, cell, settings, scored)
        row = _fork_row(cell, settings, error, scored, gap, retries)
        record(cell, row)
        if after:
            after(
                prepared,
                error,
                time.monotonic(),
                0.0,
                scored.trace if scored else None,
            )
    return row


def _in_base(
    cell: Cell, base_prepared: PreparedCell
) -> AbstractContextManager[PreparedCell]:
    memory.clear_tool_calls(base_prepared.memory)
    prepared = replace(base_prepared, cell=cell)
    if cell.scenario.fresh:
        prepared = replace(prepared, seeded=memory.read_entities(prepared.memory))
    return nullcontext(prepared)


def _chains(cells: Sequence[Cell]) -> list[tuple[Cell, list[Cell]]]:
    """Return each root cell with every follow-up below it, parents before their follow-ups."""
    chains: dict[tuple[str, Agent, int, str], tuple[Cell, list[Cell]]] = {
        (cell.variant.label, cell.agent, cell.repeat, cell.scenario.id): (cell, [])
        for cell in cells
        if cell.scenario.base is None
    }
    for cell in sorted(cells, key=lambda cell: _depth(cell.scenario)):
        if cell.scenario.base:
            key = (
                cell.variant.label,
                cell.agent,
                cell.repeat,
                cell.scenario.root.id,
            )
            chains[key][1].append(cell)
    return list(chains.values())


def chain_sizes(cells: Sequence[Cell]) -> list[int]:
    """Return how many cells each chain of ``cells`` holds, a chain running as one job."""
    return [1 + len(follow_ups) for _, follow_ups in _chains(cells)]


def _depth(scenario: Scenario) -> int:
    return _depth(scenario.base) + 1 if scenario.base else 0


class ChainRunner:
    """Runs the chains of a run on pool threads, recording a row for every cell."""

    def __init__(
        self,
        settings: Settings,
        tracker: FailFast,
        live: LiveView,
        chains: Sequence[tuple[Cell, list[Cell]]],
    ) -> None:
        self.settings = settings
        self.tracker = tracker
        self.live = live
        self.rows: dict[str, ResultRow] = {}
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._children: dict[str, list[Cell]] = defaultdict(list)
        self._gates: dict[tuple[str, Agent], threading.Event] = {}
        self._leaders: dict[tuple[str, Agent], str] = {}
        for base, follow_ups in chains:
            key = (base.variant.key, base.agent)
            self._gates.setdefault(key, threading.Event())
            self._leaders.setdefault(key, base.id)
            for cell in follow_ups:
                self._children[cast("str", cell.base_id)].append(cell)

    def _release_gates(self) -> None:
        for gate in self._gates.values():
            gate.set()

    def stop(self) -> None:
        """Stop starting cells and release the chains waiting on a gate."""
        self._stopped.set()
        self._release_gates()

    def _abort(self) -> None:
        self._release_gates()
        process.kill_all()

    def _start(self, cell: Cell) -> None:
        if self._stopped.is_set():
            raise CancelledError
        with self._lock:
            self.live.start(cell.id, label(cell))

    def _record(self, cell: Cell, row: ResultRow) -> None:
        if (reason := self.tracker.aborted) and not row.skipped:
            row = _skip_row(cell, self.settings, reason)
        self.rows[cell.id] = row
        with self._lock, (self.settings.run_dir / "results.jsonl").open("a") as handle:
            handle.write(json.dumps(row.to_json()) + "\n")
            if row.skipped:
                self.live.skip(cell.id, label(cell), row.skipped)
            else:
                self.live.finish(cell.id, row)
        if self.tracker.observe(cell, row):
            self._abort()

    def _skip(self, cell: Cell, reason: str) -> None:
        self._record(cell, _skip_row(cell, self.settings, reason))

    def _settle(self, cell: Cell, run_one: Callable[[], ResultRow]) -> None:
        if reason := self.tracker.skip_reason(cell):
            self._skip(cell, reason)
        else:
            self._start(cell)
            try:
                row = run_one()
            except Exception as exc:
                if isinstance(exc, CancelledError) or not self.tracker.enabled:
                    raise
                row = _fork_row(cell, self.settings, _error(exc), None)
            if cell.id not in self.rows:
                self._record(cell, row)

    def _settle_failed(self, cell: Cell, error: str) -> None:
        self._settle(cell, partial(_fork_row, cell, self.settings, error, None))

    def _tool(self, cell: Cell) -> Callable[[str], None]:
        return lambda name: self.live.tool(cell.id, name)

    def _spawn_follow_up(
        self,
        cell: Cell,
        open_prepared: Callable[[], AbstractContextManager[PreparedCell]],
        ended: float,
        offset: float,
        base_trace: Trace | None,
    ) -> None:
        self._settle(
            cell,
            partial(
                _run_follow_up,
                open_prepared,
                cell,
                self.settings,
                self._tool(cell),
                ended,
                offset,
                base_trace,
                self._record,
                self._follow_of(cell),
            ),
        )

    def _fail_below(self, parent: Cell, error: str) -> None:
        for cell in self._children.get(parent.id, ()):
            self._settle_failed(cell, error)
            self._fail_below(cell, error)

    def _follow_of(self, parent: Cell) -> AfterBase | None:
        if parent.id not in self._children:
            return None
        return partial(self._follow, parent)

    def _follow(
        self,
        parent: Cell,
        prepared: PreparedCell,
        error: str | None,
        ended: float,
        offset: float,
        base_trace: Trace | None,
    ) -> None:
        follow_ups = self._children[parent.id]
        if error:
            self._fail_below(parent, BASE_FAILED + error)
            return
        own = {
            cell.id: (0.0, None) if cell.scenario.fresh else (offset, base_trace)
            for cell in follow_ups
        }
        stores = self.settings.stores
        if self.settings.seen is None:
            for cell in follow_ups:
                self._spawn_follow_up(
                    cell, partial(_in_base, cell, prepared), ended, *own[cell.id]
                )
            return
        roots: list[Path] = []
        try:
            roots.extend(snapshot(prepared) for _ in follow_ups)
            shutil.rmtree(prepared.root)
            with ThreadPoolExecutor(max_workers=len(roots)) as forks:
                pending = [
                    forks.submit(
                        self._spawn_follow_up,
                        cell,
                        partial(prepare_fork, cell, root, prepared, stores),
                        ended,
                        *own[cell.id],
                    )
                    for cell, root in zip(follow_ups, roots, strict=True)
                ]
            for future in pending:
                future.result()
        finally:
            for root in roots:
                if root.exists():
                    shutil.rmtree(root)

    def _fail(self, base: Cell, follow_ups: Sequence[Cell], exc: Exception) -> None:
        error = _error(exc)
        if base.id not in self.rows:
            self._record(base, _row(base, self.settings, error, None))
        if self.rows[base.id].error:
            error = BASE_FAILED + error
        for cell in follow_ups:
            if cell.id not in self.rows:
                self._settle_failed(cell, error)

    def run_chain(self, base: Cell, follow_ups: list[Cell]) -> None:
        """Run a base cell, then its follow-ups, recording a row for each."""
        key = (base.variant.key, base.agent)
        gate, leads = self._gates[key], self._leaders[key] == base.id
        if not leads:
            gate.wait()
        try:
            if reason := self.tracker.skip_reason(base):
                self._skip(base, reason)
                for cell in follow_ups:
                    self._skip(
                        cell, self.tracker.skip_reason(cell) or BASE_SKIPPED + reason
                    )
            else:
                self._start(base)
                _run_cell(
                    base,
                    self.settings,
                    self._tool(base),
                    gate.set if leads else None,
                    Session(BASE_SESSION) if follow_ups else None,
                    self._record,
                    self._follow_of(base),
                )
        except Exception as exc:
            if isinstance(exc, CancelledError) or not self.tracker.enabled:
                self.stop()
                raise
            self._fail(base, follow_ups, exc)
        except BaseException:
            self.stop()
            raise
        finally:
            if leads:
                gate.set()
        for cell in follow_ups:
            if cell.id not in self.rows:
                self._settle_failed(cell, BASE_FAILED + "ended early")


def run(
    cells: Sequence[Cell],
    jobs: int,
    models: Mapping[Agent, str],
    run_dir: Path,
    os_sandbox: bool,
    judge: str = "auto",
    fail_fast_after: int | None = None,
) -> list[ResultRow]:
    """Run every cell on up to ``jobs`` threads and return one result row per cell.

    A base cell and its follow-ups run as one job. With ``fail_fast_after``, the first setup error
    stops the run, and a side's remaining repeats of a scenario are skipped once its first
    ``fail_fast_after`` completed repeats fail the same check. A skipped cell gets a row with a
    ``skipped`` reason.
    """
    reset_stop()
    settings = Settings(
        models,
        run_dir,
        os_sandbox,
        judge,
        cell_mount() if os_sandbox and remaps_paths() else None,
        agent_slots=threading.Semaphore(jobs),
    )
    chains = _chains(cells)
    with (
        settings.stores,
        LiveView([label(cell) for cell in cells]) as live,
        ThreadPoolExecutor(max_workers=jobs) as pool,
    ):
        runner = ChainRunner(settings, FailFast(fail_fast_after), live, chains)
        futures = [pool.submit(runner.run_chain, *chain) for chain in chains]
        try:
            for future in as_completed(futures):
                if not future.cancelled() and not isinstance(
                    future.exception(), CancelledError
                ):
                    future.result()
        except BaseException:
            runner.stop()
            for future in futures:
                future.cancel()
            process.kill_all()
            raise
    for future in futures:
        future.result()
    return [runner.rows[cell.id] for cell in cells]


def _rescore(cell: Cell, prior: ResultRow, settings: Settings) -> ResultRow:
    source = reuse.cell_dir(prior)
    destination = settings.run_dir / "cells" / cell.id
    shutil.copytree(source, destination)
    kept = saved.load(destination)
    base = prior.base
    with tempfile.TemporaryDirectory() as scratch:
        context = CheckContext(
            kept.trace,
            kept.workspace,
            kept.memory_before,
            kept.memory_after,
            settings.judge,
            saved.load(source.parent / base).trace
            if base and not cell.scenario.fresh
            else None,
            cell.scenario.ask,
            cell.variant.venv,
            SandboxPolicy((destination, Path(scratch)), (live_memory()[1],))
            if settings.os_sandbox
            else None,
            isolated_env(Path(scratch), cell.variant.venv),
        )
        scored = Scored(
            kept.trace,
            evaluate(cell.scenario.checks, context),
            metrics(kept.trace, kept.memory_before, kept.memory_after),
            kept.memory_before,
            kept.memory_after,
        )
    _save_judgements(destination, cell, scored.outcomes)
    row = _row(
        cell,
        settings,
        None,
        scored,
        isolated=prior.isolated,
        fork_gap_s=prior.fork_gap_s,
    )
    return replace(row, reused_from=reuse.origin(prior))


def rescore(
    reused: Sequence[tuple[Cell, ResultRow]],
    jobs: int,
    models: Mapping[Agent, str],
    run_dir: Path,
    os_sandbox: bool,
    judge: str = "auto",
) -> dict[str, ResultRow]:
    """Return a row by cell id for each reused cell: its saved agent run, checked again by the current scenario."""
    settings = Settings(models, run_dir, os_sandbox, judge, None)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            cell.id: pool.submit(_rescore, cell, prior, settings)
            for cell, prior in reused
        }
    return {id: future.result() for id, future in futures.items()}


def plan(
    variants: Sequence[Variant],
    agents: Sequence[Agent],
    scenarios: Sequence[Scenario],
    repeats: Sequence[int],
) -> list[Cell]:
    """Return the cells to run: every variant, agent and scenario for each of the ``repeats`` indexes."""
    return [
        Cell(variant, agent, scenario, repeat)
        for scenario in scenarios
        for agent in agents
        if agent in scenario.agents
        for repeat in repeats
        for variant in variants
    ]
