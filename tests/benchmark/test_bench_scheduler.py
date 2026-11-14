import errno
import json
import threading
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeSubprocess

from benchmark.conftest import SCENARIO, FakeAgent, FakeSandbox
from benchmark.traces import make_trace
from llm_prompts.benchmark import paths, scheduler, transient
from llm_prompts.benchmark.agents import DEFAULT_MODELS
from llm_prompts.benchmark.cell import audit
from llm_prompts.benchmark.runner import process
from llm_prompts.benchmark.types import (
    Agent,
    Cell,
    CheckSpec,
    MemoryEntity,
    Session,
    Tokens,
    ToolCall,
    Variant,
)

pytestmark = pytest.mark.usefixtures("live_home", "fake_memory", "fake_subprocess")
PASS = CheckSpec("tool_called", {"name": "ok"})
FAIL = CheckSpec("tool_called", {"name": "never-present"})
trace = partial(
    make_trace, final_text="done", tool_calls=(ToolCall("ok", {}, True),), tokens=Tokens(1, 2, 3, 4), wall_s=5.0,
    model="resolved", context=7, start_context=3, cost_usd=0.5,
)  # fmt: skip


class Go:
    def __init__(self, tmp_path: Path, variant: Variant) -> None:
        self.tmp_path, self.variant, self.run_dir = tmp_path, variant, tmp_path / "r"
        self.run_dir.mkdir()
        self.cell: Cell

    def cells(
        self, *names: str, check: CheckSpec = PASS, agent: Agent = "claude"
    ) -> list[Cell]:
        cells = []
        for name in names:
            workspace = self.tmp_path / name
            workspace.mkdir(exist_ok=True)
            scenario = replace(SCENARIO, id=name, workspace=workspace, checks=(check,))
            cells.append(Cell(self.variant, agent, scenario, 0))
        return cells

    def __call__(
        self, name: str, check: CheckSpec = PASS, sandbox: bool = False
    ) -> Any:
        (self.cell,) = self.cells(name, check=check)
        return scheduler.run([self.cell], 1, DEFAULT_MODELS, self.run_dir, sandbox)[0]


@pytest.fixture
def go(tmp_path: Path, fake_variant: Variant) -> Go:
    return Go(tmp_path, fake_variant)


def test_each_cell_becomes_a_scored_row(go: Go, fake_agent: FakeAgent) -> None:
    home = f"{Path.home()}/.local/bin/pytest"
    leak = ToolCall("Bash", {"command": home}, True)
    failed = ToolCall(
        "Bash", {"command": "pytest"}, False, error="Command exited with code 1"
    )
    passed = ToolCall("Bash", {"command": "pytest"}, True, output="2 passed")
    fake_agent.script(
        "good", trace=trace(tool_calls=(failed, passed, ToolCall("ok", {}, True)))
    )
    fake_agent.script("slow", raises=TimeoutError())
    fake_agent.script("crash", trace=trace(final_text="", exit_code=1))
    fake_agent.script("dead", trace=trace(exit_code=1, error="boom"))
    fake_agent.script("leaky", trace=trace(tool_calls=(leak,)))

    good, bad, slow, crash, dead, leaky = (
        go("good"), go("good", FAIL), go("slow"), go("crash"), go("dead"), go("leaky"),
    )  # fmt: skip

    assert (good.passed, good.error, good.model) == (True, None, "resolved")
    assert good.failed_test_runs == 1
    assert (good.follow_up_of, good.fresh) == (None, False)
    assert good.tokens == Tokens(1, 2, 3, 4)
    assert [r.error for r in (bad, slow, crash, dead)] == [
        None,
        "timeout",
        "agent exit 1: log",
        "agent exit 1: boom",
    ]
    assert (leaky.passed, leaky.error) == (
        False,
        f"isolation breach: Bash: {home}",
    )
    assert len((go.run_dir / "results.jsonl").read_text().splitlines()) == 6


def test_server_tool_calls_and_hook_log_are_kept_and_the_sandbox_policy_is_applied(
    go: Go, fake_agent: FakeAgent
) -> None:
    calls = (ToolCall("Read", {}, True, at=99.0), ToolCall("Edit", {}, True, at=105.0))
    server = (ToolCall("memory.search_nodes", {}, True, at=100.0),)
    fake_agent.script("s0", memory_calls=server, trace=trace(tool_calls=calls))

    row = go("s0", sandbox=True)

    kept = go.run_dir / "cells" / go.cell.id
    saved = json.loads((kept / "trace.json").read_text())
    assert (kept / "cline-hooks.log").read_text() == "hooks"
    assert [c["name"] for c in saved["tool_calls"]] == [
        "Read",
        "memory.search_nodes",
        "Edit",
    ]
    assert (row.memory.memory_calls, row.memory.read_before_first_edit) == (
        1,
        True,
    )
    [policy] = fake_agent.policies
    assert policy is not None
    assert fake_agent.executed[0].root in policy.writable
    assert audit.live_memory()[1] in policy.denied_ports


def test_linux_sandbox_shows_every_cell_at_the_same_path(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox
) -> None:
    fake_sandbox.present("bwrap")

    go("s0", sandbox=True)
    go("s1", sandbox=True)

    first, second = fake_agent.executed
    assert first.root != second.root
    mounts = [policy.mount for policy in fake_agent.policies if policy]
    assert mounts == [
        (first.root, paths.cell_mount()),
        (second.root, paths.cell_mount()),
    ]
    assert first.env["HOME"] == second.env["HOME"] == str(paths.cell_mount() / "home")


def test_later_cells_of_a_variant_and_agent_wait_for_the_first_reply(
    go: Go, fake_agent: FakeAgent
) -> None:
    fake_agent.script("first", trace=trace(), reply_delay=0.2)
    fake_agent.script("second", trace=trace())

    scheduler.run(go.cells("first", "second"), 2, DEFAULT_MODELS, go.run_dir, False)

    assert fake_agent.events == [
        ("start", "a-claude-first-0"),
        ("reply", "a-claude-first-0"),
        ("start", "a-claude-second-0"),
    ]


def test_later_cells_start_when_the_first_cell_ends_without_a_reply(
    go: Go, fake_agent: FakeAgent
) -> None:
    fake_agent.script("first", trace=trace(), replies=False)
    fake_agent.script("second", trace=trace())

    rows = scheduler.run(
        go.cells("first", "second"), 2, DEFAULT_MODELS, go.run_dir, False
    )

    assert [row.error for row in rows] == [None, None]


def _chain(go: Go, *follow_ups: str) -> list[Cell]:
    (root,) = go.cells("root")
    cells = [root]
    for name in follow_ups:
        scenario = replace(
            SCENARIO, id=name, workspace=root.scenario.workspace,
            checks=(PASS,), base=cells[0].scenario,
        )  # fmt: skip
        cells.append(Cell(go.variant, "claude", scenario, 0))
    return cells


def test_follow_ups_fork_the_finished_base_each_in_its_own_copy(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox
) -> None:
    fake_sandbox.present("bwrap")
    fake_agent.script("root", trace=trace(cost_usd=0.5), files={"made.txt": "x"})
    fake_agent.script("one", trace=trace(cost_usd=0.6), files={"one.txt": "x"})
    fake_agent.script("two", trace=trace(cost_usd=0.7))

    rows = scheduler.run(_chain(go, "one", "two"), 1, DEFAULT_MODELS, go.run_dir, True)

    assert fake_agent.sessions == {
        "a-claude-root-0": Session("bench-base"),
        "a-claude-one-0": Session("bench-one", "bench-base"),
        "a-claude-two-0": Session("bench-two", "bench-base"),
    }
    assert fake_agent.seen_files["a-claude-two-0"] == ["made.txt"]
    assert fake_agent.seen_files["a-claude-one-0"] == ["made.txt"]
    assert [r.base for r in rows] == [None, "a-claude-root-0", "a-claude-root-0"]
    assert [r.cost_usd for r in rows] == pytest.approx([0.5, 0.1, 0.2])
    assert [r.isolated for r in rows] == [True, True, True]
    gaps = [r.fork_gap_s for r in rows]
    assert gaps[0] is None
    assert all(0 <= gap < 300 for gap in gaps[1:])  # type: ignore[operator]
    assert len((go.run_dir / "results.jsonl").read_text().splitlines()) == 3


def test_the_base_tree_is_deleted_once_its_follow_ups_are_copied(
    go: Go,
    fake_agent: FakeAgent,
    fake_sandbox: FakeSandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sandbox.present("bwrap")
    fake_agent.script("root", trace=trace(), files={"made.txt": "x"})
    fake_agent.script("one", trace=trace())
    run_agent = process.execute
    base_existed: list[bool] = []

    def watching(prepared: Any, *args: Any, **kwargs: Any) -> Any:
        if prepared.cell.id == "a-claude-one-0":
            base_existed.append(base_root[0].exists())
        else:
            base_root.append(prepared.root)
        return run_agent(prepared, *args, **kwargs)

    base_root: list[Path] = []
    monkeypatch.setattr(process, "execute", watching)

    scheduler.run(_chain(go, "one"), 1, DEFAULT_MODELS, go.run_dir, True)

    assert base_existed == [False]


def test_forked_follow_ups_never_run_more_agents_at_once_than_jobs(
    go: Go,
    fake_agent: FakeAgent,
    fake_sandbox: FakeSandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sandbox.present("bwrap")
    for name in ("one", "two", "three"):
        fake_agent.script(name, trace=trace(), reply_delay=0.05)
    lock, active, peak = threading.Lock(), [0], [0]
    run_agent = process.execute

    def counted(*args: Any, **kwargs: Any) -> Any:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            return run_agent(*args, **kwargs)
        finally:
            with lock:
                active[0] -= 1

    monkeypatch.setattr(process, "execute", counted)

    scheduler.run(
        _chain(go, "one", "two", "three"), 2, DEFAULT_MODELS, go.run_dir, True
    )

    assert peak[0] == 2


def _fresh_chain(go: Go, check: CheckSpec = PASS) -> list[Cell]:
    root, one = _chain(go, "one")
    later = replace(
        one.scenario, id="later", base=one.scenario, fresh=True, checks=(check,)
    )
    return [root, one, Cell(go.variant, "claude", later, 0)]


@pytest.mark.parametrize("isolated", [True, False])
def test_fresh_follow_up_of_a_follow_up_starts_a_new_session_on_the_files_and_memory_so_far(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox, isolated: bool
) -> None:
    fake_sandbox.present("bwrap")
    fake_agent.script(
        "root", trace=trace(cost_usd=0.5), entities=(MemoryEntity("task/a", "task", ("x",)),)
    )  # fmt: skip
    fake_agent.script(
        "one", trace=trace(cost_usd=0.6), files={"one.txt": "x"},
        entities=(MemoryEntity("task/b", "task", ("y",)),),
    )  # fmt: skip
    fake_agent.script("later", trace=trace(cost_usd=0.7))

    rows = scheduler.run(
        _fresh_chain(go, CheckSpec("memory_written", {"name_regex": "."})),
        1, DEFAULT_MODELS, go.run_dir, isolated,
    )  # fmt: skip

    assert fake_agent.sessions["a-claude-later-0"] is None
    assert fake_agent.seen_files["a-claude-later-0"] == ["one.txt"]
    assert [r.base for r in rows] == [None, "a-claude-root-0", "a-claude-one-0"]
    assert [(r.follow_up_of, r.fresh) for r in rows] == [
        (None, False), ("root", False), ("one", True),
    ]  # fmt: skip
    assert rows[2].cost_usd == pytest.approx(0.7)
    assert rows[2].memory.entities_added == 0
    assert not rows[2].passed


def test_a_fresh_follow_up_does_not_see_the_sessions_of_the_follow_up_before_it(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    fake_sandbox.present("bwrap")
    sessions = Path(".pi/agent/sessions")

    def execute(prepared: Any, *args: Any, **kwargs: Any) -> Any:
        (prepared.home / sessions).mkdir(parents=True, exist_ok=True)
        (prepared.home / sessions / "one.jsonl").write_text("x")
        return fake_agent.execute(prepared, *args, **kwargs)

    monkeypatch.setattr(process, "execute", execute)

    scheduler.run(_fresh_chain(go), 1, DEFAULT_MODELS, go.run_dir, True)

    later = next(p for p in fake_agent.executed if p.cell.id == "a-claude-later-0")
    assert not (later.home / sessions).exists()


def test_a_failed_follow_up_gives_the_fresh_follow_up_after_it_an_error_row(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox
) -> None:
    fake_sandbox.present("bwrap")
    fake_agent.script("one", raises=TimeoutError())

    rows = scheduler.run(_fresh_chain(go), 1, DEFAULT_MODELS, go.run_dir, True)

    assert [r.error for r in rows] == [None, "timeout", "base failed: timeout"]


def test_follow_ups_without_an_isolated_copy_run_one_after_another_in_the_base(
    go: Go, fake_agent: FakeAgent
) -> None:
    fake_agent.script("root", trace=trace(), files={"made.txt": "x"})
    fake_agent.script("one", trace=trace(), files={"one.txt": "x"})

    rows = scheduler.run(_chain(go, "one", "two"), 1, DEFAULT_MODELS, go.run_dir, False)

    assert fake_agent.seen_files["a-claude-two-0"] == ["made.txt", "one.txt"]
    assert [r.isolated for r in rows] == [True, False, False]
    assert len({p.root for p in fake_agent.executed}) == 1


@pytest.mark.parametrize("isolated", [True, False])
def test_follow_up_memory_checks_count_what_the_base_wrote(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox, isolated: bool
) -> None:
    fake_sandbox.present("bwrap")
    feature = MemoryEntity("feature/demo/f", "feature", ("what it is for",))
    fake_agent.script("root", trace=trace(), entities=(feature,))
    fake_agent.script("one", trace=trace())
    root, one = _chain(go, "one")
    written = CheckSpec("memory_written", {"name_regex": "^feature/demo/"})
    one = replace(one, scenario=replace(one.scenario, checks=(written,)))

    rows = scheduler.run([root, one], 1, DEFAULT_MODELS, go.run_dir, isolated)

    assert rows[1].passed


@pytest.mark.parametrize("isolated", [True, False])
def test_follow_up_memory_judge_sees_the_base_ask_and_what_the_base_and_follow_up_wrote(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox,
    fake_subprocess: FakeSubprocess, judge_passes: None, isolated: bool,
) -> None:  # fmt: skip
    fake_sandbox.present("bwrap")
    fake_agent.script(
        "root",
        trace=trace(),
        entities=(MemoryEntity("task/t", "task", ("from base",)),),
    )
    fake_agent.script(
        "one",
        trace=trace(),
        entities=(MemoryEntity("task/t", "task", ("from wrap-up",)),),
    )
    root, one = _chain(go, "one")
    root = replace(root, scenario=replace(root.scenario, prompt="Add a tag filter"))
    judged = CheckSpec("judge", {"rubric": "r", "memory": True})
    one = replace(
        one,
        scenario=replace(one.scenario, base=root.scenario, checks=(judged,)),
    )

    scheduler.run([root, one], 1, DEFAULT_MODELS, go.run_dir, isolated, "claude")

    (_, kwargs), *_ = (c for c in fake_subprocess.calls if c[0][0] == "claude")
    assert "task/t: from base" in kwargs["input"]
    assert "task/t: from wrap-up" in kwargs["input"]
    assert "User's ask:\nAdd a tag filter" in kwargs["input"]


@pytest.mark.parametrize("isolated", [True, False])
def test_follow_up_failed_calls_judge_sees_the_failures_of_the_base_session(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox,
    fake_subprocess: FakeSubprocess, judge_passes: None, isolated: bool,
) -> None:  # fmt: skip
    fake_sandbox.present("bwrap")
    failure = ToolCall("Bash", {"command": "pytest"}, False, error="unknown env")
    fake_agent.script("root", trace=trace(tool_calls=(failure,)))
    fake_agent.script("one", trace=trace())
    root, one = _chain(go, "one")
    judged = CheckSpec("judge", {"rubric": "r", "failed": True})
    one = replace(one, scenario=replace(one.scenario, checks=(judged,)))

    scheduler.run([root, one], 1, DEFAULT_MODELS, go.run_dir, isolated, "claude")

    (_, kwargs), *_ = (c for c in fake_subprocess.calls if c[0][0] == "claude")
    assert (
        "Rejected tool calls (base session):\nREJECTED (not saved): Bash args=pytest error=unknown env"
        in kwargs["input"]
    )
    assert "Rejected tool calls (this session): none" in kwargs["input"]


@pytest.mark.parametrize("fail_fast_after", [None, 3])
def test_a_failed_base_gives_its_follow_ups_an_error_row_and_no_agent_run(
    go: Go, fake_agent: FakeAgent, fail_fast_after: int | None
) -> None:
    fake_agent.script("root", raises=TimeoutError())

    rows = scheduler.run(
        _chain(go, "one"), 1, DEFAULT_MODELS, go.run_dir, False,
        fail_fast_after=fail_fast_after,
    )  # fmt: skip

    assert [(r.error, r.skipped) for r in rows] == [
        ("timeout", None),
        ("base failed: timeout", None),
    ]
    assert [p.cell.id for p in fake_agent.executed] == ["a-claude-root-0"]


def test_interrupt_kills_running_agents(
    go: Go, fake_agent: FakeAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[bool] = []
    monkeypatch.setattr(process, "kill_all", lambda: killed.append(True))
    fake_agent.script("s0", raises=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        go("s0")

    assert killed


def test_fail_fast_stops_at_the_first_setup_error_and_skips_the_rest(
    go: Go, fake_agent: FakeAgent
) -> None:
    fake_agent.script("one", trace=trace(exit_code=1, error="auth failed"))
    cells = go.cells("one", "two", "three")

    rows = scheduler.run(cells, 1, DEFAULT_MODELS, go.run_dir, False, fail_fast_after=3)

    assert [p.cell.id for p in fake_agent.executed] == ["a-claude-one-0"]
    assert [r.error for r in rows] == ["agent exit 1: auth failed", None, None]
    assert [r.skipped for r in rows] == [
        None,
        *["setup error: agent exit 1: auth failed"] * 2,
    ]
    assert [r.cell_id for r in rows] == [c.id for c in cells]
    assert len((go.run_dir / "results.jsonl").read_text().splitlines()) == 3


@pytest.mark.parametrize("failing", ["snapshot", "prepare_fork"])
def test_fail_fast_treats_a_full_disk_while_copying_a_follow_up_as_a_setup_error(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox,
    monkeypatch: pytest.MonkeyPatch, failing: str,
) -> None:  # fmt: skip
    def full_disk(*args: Any) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    fake_sandbox.present("bwrap")
    fake_agent.script("root", trace=trace())
    monkeypatch.setattr(scheduler, failing, full_disk)
    cells = [*_chain(go, "one"), *go.cells("later")]

    rows = scheduler.run(cells, 1, DEFAULT_MODELS, go.run_dir, True, fail_fast_after=3)

    error = "OSError: [Errno 28] No space left on device"
    assert [(r.error, r.skipped) for r in rows] == [
        (None, None),
        (error, None),
        (None, f"setup error: {error}"),
    ]


def _repeats(go: Go, name: str, count: int, *checks: CheckSpec) -> list[Cell]:
    workspace = go.tmp_path / name
    workspace.mkdir(exist_ok=True)
    scenario = replace(SCENARIO, id=name, workspace=workspace, checks=checks)
    return [Cell(go.variant, "claude", scenario, repeat) for repeat in range(count)]


def test_fail_fast_skips_the_rest_of_a_scenario_after_n_repeats_fail_the_same_check(
    go: Go, fake_agent: FakeAgent
) -> None:
    fake_agent.script("s0", trace=trace())

    rows = scheduler.run(
        _repeats(go, "s0", 5, PASS, FAIL), 1, DEFAULT_MODELS, go.run_dir, False,
        fail_fast_after=3,
    )  # fmt: skip

    assert [r.skipped for r in rows] == [None] * 3 + [
        "first 3 repeats all failed tool_called(name=never-present)"
    ] * 2
    assert [r.repeat for r in rows if not r.skipped] == [0, 1, 2]
    assert len(fake_agent.executed) == 3


def test_fail_fast_marks_cells_still_running_at_the_abort_as_skipped_and_leaves_no_temp_dirs(
    go: Go, fake_agent: FakeAgent, tmp_path: Path
) -> None:
    slow, boom = go.cells("slow", "boom")
    slow = replace(slow, agent="pi")
    fake_agent.script("slow", trace=trace(), reply_delay=0.3)
    fake_agent.script("boom", raises=RuntimeError("disk full"))

    rows = scheduler.run(
        [slow, boom], 2, DEFAULT_MODELS, go.run_dir, False, fail_fast_after=3
    )

    assert [(r.error, r.skipped) for r in rows] == [
        (None, "setup error: RuntimeError: disk full"),
        ("RuntimeError: disk full", None),
    ]
    assert list((tmp_path / "roots").iterdir()) == []


def test_cells_run_with_one_read_only_npm_store_that_the_run_deletes(
    go: Go, fake_agent: FakeAgent, fake_sandbox: FakeSandbox
) -> None:
    fake_sandbox.present("bwrap")
    npm = go.variant.templates["pi"] / ".pi/agent/npm/node_modules/pkg/index.js"
    npm.parent.mkdir(parents=True)
    npm.write_text("x")
    cells = go.cells("s0", "s1", agent="pi")
    for cell in cells:
        fake_agent.script(cell.scenario.id, trace=trace())

    scheduler.run(cells, 2, DEFAULT_MODELS, go.run_dir, True)

    stores = {policy.read_only for policy in fake_agent.policies if policy}
    [[store]] = stores
    assert store.name.startswith(paths.SHARED_ROOT_PREFIX)
    assert not store.exists()


THROTTLED = "Credential export failed because the credential service is throttling requests (Rate exceeded)."


def test_a_cell_whose_agent_dies_throttled_before_its_first_turn_runs_again_after_a_pause(
    go: Go, fake_agent: FakeAgent, pauses: list[float]
) -> None:
    throttled = trace(
        exit_code=1, error=THROTTLED, tokens=Tokens(), cost_usd=0.25, tool_calls=()
    )
    fake_agent.script("s0", earlier=(throttled,), trace=trace(turns=1))

    row = go("s0")

    assert (row.passed, row.error) == (True, None)
    assert (row.retries, row.retry_cost_usd, row.startup_error) == (
        1,
        0.25,
        False,
    )
    assert [p.cell.id for p in fake_agent.executed] == ["a-claude-s0-0"] * 2
    assert len(pauses) == 1 and 30 <= pauses[0] <= 60


@pytest.mark.parametrize(
    "error",
    [
        THROTTLED,
        "API Error: Could not load AWS credentials. Check your credentials.",
        "Region is missing",
    ],
    ids=["throttled", "no-credentials", "any-message"],
)
def test_an_exit_with_no_tokens_or_tool_calls_that_counts_as_the_first_turn_is_retried(
    go: Go, fake_agent: FakeAgent, pauses: list[float], error: str
) -> None:
    failed = trace(exit_code=1, error=error, turns=1, tokens=Tokens(), tool_calls=())
    fake_agent.script("s0", earlier=(failed,), trace=trace(turns=1))

    row = go("s0")

    assert (row.error, row.retries) == (None, 1)
    assert len(pauses) == 1


def test_a_cell_still_throttled_after_three_retries_is_a_startup_error_row_and_other_failures_are_not_retried(
    go: Go, fake_agent: FakeAgent, pauses: list[float]
) -> None:
    throttled = trace(exit_code=1, error=THROTTLED, tokens=Tokens(), tool_calls=())
    fake_agent.script("stuck", trace=throttled)
    fake_agent.script("partial", trace=replace(throttled, tokens=Tokens(1, 2, 3, 4)))

    stuck, partial = go("stuck"), go("partial")

    assert stuck.error == f"startup error: agent exit 1: {THROTTLED}"
    assert (stuck.startup_error, stuck.retries, stuck.passed) == (
        True,
        3,
        False,
    )
    assert (partial.startup_error, partial.retries) == (False, 0)
    assert [p.cell.id for p in fake_agent.executed].count("a-claude-stuck-0") == 4
    assert len(pauses) == 3


def test_a_throttled_follow_up_runs_again_in_its_base_and_follow_ups_of_a_throttled_base_are_startup_errors(
    go: Go, fake_agent: FakeAgent, pauses: list[float]
) -> None:
    throttled = trace(exit_code=1, error=THROTTLED, tokens=Tokens(), tool_calls=())
    fake_agent.script("one", earlier=(throttled,), trace=trace(turns=1))
    fake_agent.script("root", trace=trace(turns=1))

    rows = scheduler.run(_chain(go, "one"), 1, DEFAULT_MODELS, go.run_dir, False)

    assert [(r.error, r.retries) for r in rows] == [(None, 0), (None, 1)]
    assert len(pauses) == 1

    fake_agent.script("root", trace=throttled)

    rows = scheduler.run(_chain(go, "one"), 1, DEFAULT_MODELS, go.run_dir, False)

    assert [r.startup_error for r in rows] == [True, True]
    assert str(rows[1].error).startswith("base failed: startup error: ")


def test_agent_launches_are_spaced_out_so_parallel_cells_do_not_ask_for_credentials_at_once(
    go: Go, fake_agent: FakeAgent, pauses: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transient, "STAGGER_S", 3.0)

    scheduler.run(go.cells("one", "two", "three"), 1, DEFAULT_MODELS, go.run_dir, False)

    assert len(pauses) == 2
    assert 2.5 < pauses[0] <= 3
    assert 5.5 < pauses[1] <= 6
