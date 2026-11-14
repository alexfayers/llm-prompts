import json
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from conftest import FakeSubprocess, run_capturing_exit

from benchmark.conftest import BenchDirs, FakeAgent, FakeSandbox, pi_settings_path
from benchmark.traces import make_trace
from llm_prompts import setup
from llm_prompts.benchmark import command, paths
from llm_prompts.benchmark.agents import DEFAULT_MODELS
from llm_prompts.benchmark.agents.adapter import VariantBuildError
from llm_prompts.benchmark.cell import variants
from llm_prompts.benchmark.cell.memory import MemoryStartError
from llm_prompts.benchmark.command import RunOptions
from llm_prompts.benchmark.runner import process
from llm_prompts.benchmark.types import PreparedCell, Tokens, ToolCall, Variant
from llm_prompts.cli import main

pytestmark = pytest.mark.usefixtures(
    "live_home", "fake_memory", "bench_dirs", "fake_subprocess"
)
SCENARIO_TOML = """\
id = "{}"
level = "{}"
workspace = "ws"
project = "demo"
prompt = "Do the thing."
{}
[[check]]
kind = "tool_called"
name = "ok"
"""
trace = make_trace
OK = (ToolCall("ok", {}, True),)


@pytest.fixture(autouse=True)
def judge_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    real = shutil.which

    def which(name: str, *a: Any, **k: Any) -> str | None:
        if name in ("claude", "pi"):
            return "/usr/bin/claude" if name == "claude" else None
        return real(name, *a, **k)

    monkeypatch.setattr(shutil, "which", which)


class Builds:
    def __init__(self, variant: Variant) -> None:
        self.labels: list[str] = []
        self.args: dict[str, tuple[Any, ...]] = {}
        self.error: Exception | None = None
        self.variant = variant

    def build(self, label: str, *args: Any) -> Variant:
        self.labels.append(label)
        self.args[label] = args
        if self.error:
            raise self.error
        return replace(self.variant, label="a" if label == "a" else "b")


@pytest.fixture
def builds(fake_variant: Variant, monkeypatch: pytest.MonkeyPatch) -> Builds:
    recorder = Builds(fake_variant)
    monkeypatch.setattr(variants, "build", recorder.build)
    return recorder


@pytest.fixture
def add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    (tmp_path / "fixtures" / "ws").mkdir(parents=True)
    monkeypatch.setattr("llm_prompts.benchmark.scenarios.loader.DATA_DIR", tmp_path)

    def add(name: str = "s1", level: str = "light", extra: str = "") -> None:
        (tmp_path / f"{name}.toml").write_text(SCENARIO_TOML.format(name, level, extra))

    add(extra='agents = ["claude"]')
    return add


def run(**kwargs: Any) -> int:
    return command.run(
        RunOptions(**{"agents": ("claude",), "os_sandbox": False, **kwargs})
    )


def test_identical_scores_return_0_and_write_report(
    bench_dirs: BenchDirs, builds: Builds, add: Any, fake_agent: FakeAgent,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    fake_agent.script("s1", trace=trace(tool_calls=OK))

    assert run() == 0

    (run_dir,) = (bench_dirs.state / "runs").iterdir()
    out = capsys.readouterr().out
    assert out.splitlines()[-2:] == [
        f"Report: {run_dir}/report.md",
        f"JSON: {run_dir}/report.json",
    ]
    assert json.loads((run_dir / "report.json").read_text())["verdict"] == "ok"
    assert "| Scenario |" in (run_dir / "report.md").read_text()
    assert (run_dir / "results.jsonl").is_file()


def _results(bench_dirs: BenchDirs, run_id: str) -> list[dict[str, Any]]:
    path = bench_dirs.state / "runs" / run_id / "results.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def run_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = iter(f"20260101-0000{n:02d}-aaaa" for n in range(10))
    monkeypatch.setattr(paths, "new_run_id", lambda now=None: next(ids))


def test_a_cells_are_reused_automatically_from_the_latest_matching_run_and_marked(
    bench_dirs: BenchDirs, builds: Builds, add: Any, fake_agent: FakeAgent,
    capsys: pytest.CaptureFixture[str], run_ids: None,
) -> None:  # fmt: skip
    fake_agent.script("s1", trace=trace(tool_calls=OK, cost_usd=0.5))
    assert run() == 0
    fake_agent.executed.clear()
    assert run(reuse=False) == 0
    assert [p.cell.variant.label for p in fake_agent.executed] == ["a", "b"]
    fake_agent.executed.clear()
    capsys.readouterr()

    assert run() == 0

    assert fake_agent.executed == []
    reused = [
        r for r in _results(bench_dirs, "20260101-000002-aaaa") if r["variant"] == "a"
    ]
    assert [(r["run_id"], r["reused_from"], r["cost_usd"]) for r in reused] == [
        ("20260101-000002-aaaa", "20260101-000001-aaaa", 0.5)
    ]
    captured = capsys.readouterr()
    assert "benchmark: reused s1 claude " in captured.err
    assert "from 20260101-000001-aaaa" in captured.err
    report = (
        bench_dirs.state / "runs" / "20260101-000002-aaaa" / "report.md"
    ).read_text()
    assert "1/1 [21%-100%] (reused from 20260101-000001-aaaa, re-judged)" in report
    assert "Reused runs: 2 from 20260101-000001-aaaa" in report


@pytest.mark.parametrize(
    "changed",
    ['setup = ["git branch x"]', "delegation = true"],
    ids=["setup", "delegation"],
)
def test_a_cell_is_not_reused_after_its_setup_commands_or_delegation_change(
    builds: Builds, add: Any, fake_agent: FakeAgent, run_ids: None, changed: str
) -> None:
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    assert run() == 0
    add(extra=f'agents = ["claude"]\n{changed}')
    fake_agent.executed.clear()

    assert run() == 0

    assert [p.cell.variant.label for p in fake_agent.executed] == ["a", "b"]


def _only_check(tmp_path: Path, check: str) -> None:
    scenario = SCENARIO_TOML.format("s1", "light", 'agents = ["claude"]')
    (tmp_path / "s1.toml").write_text(
        scenario.split("[[check]]")[0] + f"[[check]]\n{check}\n"
    )


def _file_check(tmp_path: Path, regex: str) -> None:
    _only_check(tmp_path, f'kind = "file_regex"\npath = "out.txt"\nregex = "{regex}"')


def test_a_reused_after_its_checks_change_keeps_the_agent_cell_and_runs_the_new_checks(
    tmp_path: Path, bench_dirs: BenchDirs, builds: Builds, add: Any,
    fake_agent: FakeAgent, run_ids: None,
) -> None:  # fmt: skip
    fake_agent.script(
        "s1", trace=trace(tool_calls=OK, cost_usd=0.5), files={"out.txt": "foo"}
    )
    _file_check(tmp_path, "foo")
    assert run() == 0
    _file_check(tmp_path, "bar")
    fake_agent.executed.clear()

    run()

    assert fake_agent.executed == []
    (kept,) = [
        r for r in _results(bench_dirs, "20260101-000001-aaaa") if r["variant"] == "a"
    ]
    assert (kept["reused_from"], kept["cost_usd"], kept["passed"]) == (
        "20260101-000000-aaaa",
        0.5,
        False,
    )
    assert kept["checks"][0]["detail"] == "'out.txt' lacks 'bar'"


def test_each_judge_reason_is_kept_in_full_per_cell_and_listed_in_the_report(
    tmp_path: Path, bench_dirs: BenchDirs, builds: Builds, add: Any,
    fake_agent: FakeAgent, fake_subprocess: FakeSubprocess, run_ids: None,
) -> None:  # fmt: skip
    reason = ("Clause 2 fails: " + "the tests never assert the error. " * 5).strip()
    reply = json.dumps({"type": "result", "result": f"FAIL\n{reason}", "usage": {}})
    fake_subprocess.on_match(lambda argv: argv[0] == "claude", stdout=reply)
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    _only_check(tmp_path, 'kind = "judge"\nrubric = "Old rubric."')
    run()
    _only_check(tmp_path, 'kind = "judge"\nrubric = "New rubric."')
    fake_agent.executed.clear()

    run()

    for run_id in ("20260101-000000-aaaa", "20260101-000001-aaaa"):
        cells = bench_dirs.state / "runs" / run_id / "cells"
        for cell_dir in cells.iterdir():
            text = (cell_dir / "judge-1.txt").read_text()
            assert text.endswith(f"\n{reason}\n")
    rubrics = [
        (cell_dir / "judge-1.txt").read_text().splitlines()[1]
        for cell_dir in (
            bench_dirs.state / "runs" / "20260101-000001-aaaa" / "cells"
        ).iterdir()
    ]
    assert rubrics == ["New rubric."] * 2
    for row in _results(bench_dirs, "20260101-000001-aaaa"):
        assert row["checks"][0]["detail"].endswith(f"\n{reason}")
    report = (
        bench_dirs.state / "runs" / "20260101-000001-aaaa" / "report.md"
    ).read_text()
    assert (
        f"## Judge reasons\n\n- s1 claude A #1: judge said FAIL on: New rubric. {reason}"
        in report
    )


def test_a_without_saved_outputs_is_not_reused(
    tmp_path: Path, bench_dirs: BenchDirs, builds: Builds, add: Any,
    fake_agent: FakeAgent, run_ids: None,
) -> None:  # fmt: skip
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    run()
    shutil.rmtree(bench_dirs.state / "runs" / "20260101-000000-aaaa" / "cells")
    fake_agent.executed.clear()

    run()

    assert [p.cell.variant.label for p in fake_agent.executed] == ["a", "b"]


def test_a_fresh_follow_up_of_a_follow_up_is_reused_together_with_all_its_ancestors(
    tmp_path: Path, builds: Builds, add: Any, fake_agent: FakeAgent
) -> None:
    for name, base, extra in (("f1", "s1", ""), ("g1", "f1", "fresh = true\n")):
        (tmp_path / f"{name}.toml").write_text(
            f'id = "{name}"\nlevel = "light"\nbase = "{base}"\n{extra}prompt = "More."\n'
            '[[check]]\nkind = "tool_called"\nname = "ok"\n'
        )
        fake_agent.script(name, trace=trace(tool_calls=OK))
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    run()
    fake_agent.executed.clear()

    assert run() == 0

    assert fake_agent.executed == []


def test_marking_a_scenario_as_the_headline_does_not_stop_its_a_cell_being_reused(
    builds: Builds, add: Any, fake_agent: FakeAgent
) -> None:
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    run()
    add(extra='agents = ["claude"]\nheadline = true')
    fake_agent.executed.clear()

    assert run() == 0

    assert fake_agent.executed == []


def test_a_with_an_unpinned_tool_source_warns_and_runs_fresh(
    builds: Builds, add: Any, fake_agent: FakeAgent, capsys: pytest.CaptureFixture[str]
) -> None:
    builds.variant = replace(builds.variant, build=None)
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    run()
    fake_agent.executed.clear()

    assert run() == 0

    assert "not pinned" in capsys.readouterr().err
    assert [p.cell.variant.label for p in fake_agent.executed] == ["a", "b"]


def test_a_not_reused_names_the_part_that_differs_from_the_closest_earlier_run(
    builds: Builds, add: Any, fake_agent: FakeAgent, capsys: pytest.CaptureFixture[str],
    run_ids: None,
) -> None:  # fmt: skip
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    run()
    builds.variant = replace(builds.variant, build={"claude": "other-build"})
    capsys.readouterr()

    run()

    assert (
        "benchmark: not reused s1 claude main #1: build differs from 20260101-000000-aaaa"
        in capsys.readouterr().err
    )


def test_each_variant_is_built_with_its_own_tool_sources(
    builds: Builds, add: Any, fake_agent: FakeAgent
) -> None:
    fake_agent.script("s1", trace=trace(tool_calls=OK))

    run(a_tools={"mcp-memory": "/m/a"}, b_tools={"mcp-memory": "/m/b"})

    assert builds.args["a"][-1] == {"mcp-memory": "/m/a"}
    assert builds.args["b"][-1] == {"mcp-memory": "/m/b"}


def test_configured_tools_missing_from_this_python_are_installed(
    tmp_path: Path, builds: Builds, add: Any, fake_agent: FakeAgent,
    fake_subprocess: FakeSubprocess,
) -> None:  # fmt: skip
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    absent = tmp_path / "absent-tool"
    absent.mkdir()
    (absent / "pyproject.toml").write_text('[project]\nname = "absent-tool"\n')
    setup.config_path().write_text(
        f'[[tools]]\nname = "pytest"\nsource = "git+https://example.invalid/p.git"\n'
        f'[[tools]]\nname = "absent-tool"\nsource = "{absent}"\n'
    )

    assert run() == 0

    (install,) = [
        c for c in fake_subprocess.commands if c[:3] == ["uv", "pip", "install"]
    ]
    assert install[3:5] == ["--python", sys.executable]
    assert str(absent) in install
    assert not any("example.invalid" in arg for arg in install)


def test_b_failing_a_passing_check_returns_1(
    builds: Builds, add: Any, monkeypatch: pytest.MonkeyPatch, fake_agent: FakeAgent
) -> None:
    def execute(prepared: PreparedCell, *args: Any) -> Any:
        return trace(tool_calls=OK if prepared.cell.variant.label == "a" else ())

    monkeypatch.setattr(process, "execute", execute)

    assert run(repeats=12) == 1


@pytest.mark.parametrize(
    "error",
    [
        VariantBuildError("b", "x"),
        MemoryStartError("x"),
        subprocess.CalledProcessError(1, "u"),
    ],
)
def test_setup_failure_returns_2_without_running_cells(
    builds: Builds, add: Any, fake_agent: FakeAgent, error: Exception
) -> None:
    builds.error = error

    assert run() == 2
    assert fake_agent.executed == []


def test_other_failures_return_2(
    builds: Builds, add: Any, fake_agent: FakeAgent, fake_sandbox: FakeSandbox,
    fake_variant: Variant, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    assert command.run(RunOptions(agents=("claude",), os_sandbox=True)) == 2
    assert builds.labels == []
    add("heavy-one", "heavy")
    assert run(scenarios=("heavy-one",)) == 2
    add("c1", extra='agents = ["claude"]')
    assert run(scenarios=("c1",), agents=("pi",)) == 2
    assert run(agents=("pi",)) == 2
    fake_agent.script("s1", raises=RuntimeError("crashed"))
    assert run(scenarios=("s1",)) == 2
    leak = fake_variant.templates["claude"] / ".claude" / "leak.txt"
    leak.write_text(f"path {Path.home() / '.claude'}\n")
    fake_agent.executed.clear()
    assert run(scenarios=("s1",)) == 2
    assert "leak.txt" in capsys.readouterr().err
    assert fake_agent.executed == []


def test_missing_judge_harness_stops_the_run_before_building(
    builds: Builds, add: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(judge="pi") == 2
    assert "pi" in capsys.readouterr().err
    assert builds.labels == []


def cli(*argv: str, returns: int = 0) -> tuple[int | str | None, list[RunOptions]]:
    with (
        patch("sys.argv", ["llm-prompts", "benchmark", *argv]),
        patch("llm_prompts.benchmark.command.run", return_value=returns) as mock,
    ):
        return run_capturing_exit(main), [c.args[0] for c in mock.call_args_list]


def test_cli_options_reach_run_options_and_exit_code_is_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        setup, "read_config", lambda: {"tools": [{"name": "other", "source": "/o"}]}
    )
    code, defaults = cli(returns=1)
    _, calls = cli(
        *["--a", "v1", "--b", "v2", "--level", "medium", "--agents", "pi,claude,pi"],
        *[
            "--model",
            "pi=x",
            "--repeats",
            "4",
            "--max-repeats",
            "2",
            "-j",
            "2",
            "--scenario",
            "s1",
        ],
        *["--overlay", "other", "--no-os-sandbox"],
        *["--judge", "claude"],
        *["--a-tool", "mcp-memory=/m/a", "--b-tool", "mcp-memory=/m/b"],
        *["--b-env", "FLAG=0"],
    )

    assert (code, defaults) == (1, [RunOptions()])
    assert calls == [
        RunOptions(
            a="v1", b="v2", level="medium", agents=("pi", "claude"),
            models={**DEFAULT_MODELS, "pi": "x"}, repeats=4, max_repeats=2, jobs=2, scenarios=("s1",),
            overlays=("other",), os_sandbox=False, judge="claude",
            a_tools={"mcp-memory": "/m/a"}, b_tools={"mcp-memory": "/m/b"},
            b_env={"FLAG": "0"},
        )
    ]  # fmt: skip


def test_a_missing_pi_default_model_is_a_usage_error_only_when_pi_is_run() -> None:
    pi_settings_path().unlink()

    assert cli("--agents", "pi") == (2, [])
    assert cli("--agents", "pi", "--model", "pi=x")[0] == 0
    code, (options,) = cli("--agents", "claude")
    assert (code, options.models) == (0, {"claude": "sonnet"})


def test_overlays_are_off_unless_asked_for_all_or_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = ["llm-prompts", "cline-hooks", "mcp-memory", "one", "two"]
    config = {"tools": [{"name": name, "source": f"/{name}"} for name in tools]}
    monkeypatch.setattr(setup, "read_config", lambda: config)

    _, (default,) = cli()
    _, (every,) = cli("--overlays")
    _, (named,) = cli("--overlay", "two")

    assert (default.overlays, every.overlays, named.overlays) == (
        (),
        ("one", "two"),
        ("two",),
    )
    for core in ("mcp-memory", "missing"):
        _, calls = cli("--overlay", core)
        assert calls == []


def test_fail_fast_is_off_by_default_and_its_threshold_is_three_unless_set() -> None:
    _, (default,) = cli()
    _, (enabled,) = cli("--fail-fast")
    _, (tuned,) = cli("--fail-fast", "--fail-fast-after", "5")

    assert (default.fail_fast, default.fail_fast_after) == (False, 3)
    assert (enabled.fail_fast, enabled.fail_fast_after) == (True, 3)
    assert (tuned.fail_fast, tuned.fail_fast_after) == (True, 5)


def test_jobs_come_from_the_config_and_the_flag_overrides_them() -> None:
    config = setup.config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[benchmark]\njobs = 6\n")

    _, (configured,) = cli()
    _, (flagged,) = cli("-j", "2")

    assert (configured.jobs, flagged.jobs) == (6, 2)


@pytest.mark.parametrize(
    "flags",
    [
        ["--level", "x"],
        ["--agents", "gemini"],
        ["--model", "id"],
        ["--a-tool", "mcp-memory"],
        ["--repeats", "0"],
        ["-j", "0"],
        ["--fail-fast-after", "0"],
    ],
)
def test_bad_value_is_a_usage_error(flags: list[str]) -> None:
    assert cli(*flags) == (2, [])


def test_fail_fast_aborts_on_a_setup_error_reports_the_skipped_cells_and_never_reuses_them(
    bench_dirs: BenchDirs, builds: Builds, add: Any, fake_agent: FakeAgent,
    capsys: pytest.CaptureFixture[str], run_ids: None,
) -> None:  # fmt: skip
    add("s2", extra='agents = ["claude"]')
    fake_agent.script(
        "s1", trace=trace(exit_code=1, error="auth failed", tool_calls=OK)
    )

    assert run(fail_fast=True, jobs=1) == 2

    rows = _results(bench_dirs, "20260101-000000-aaaa")
    reason = "setup error: agent exit 1: auth failed"
    assert [(r["cell_id"], r["skipped"]) for r in rows] == [
        ("a-claude-s1-0", None), ("b-claude-s1-0", reason), ("a-claude-s2-0", reason),
        ("b-claude-s2-0", reason),
    ]  # fmt: skip
    assert [p.cell.id for p in fake_agent.executed] == ["a-claude-s1-0"]
    report = (
        bench_dirs.state / "runs" / "20260101-000000-aaaa" / "report.md"
    ).read_text()
    assert "Gate: aborted by a setup error." in report
    assert f"- s2 claude A: #1 skipped, {reason}" in report
    assert reason in capsys.readouterr().err

    fake_agent.executed.clear()
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    fake_agent.script("s2", trace=trace(tool_calls=OK))
    assert run() == 0
    assert sorted(p.cell.id for p in fake_agent.executed) == [
        "a-claude-s1-0", "a-claude-s2-0", "b-claude-s1-0", "b-claude-s2-0",
    ]  # fmt: skip


def test_scenario_option_can_name_several_scenarios(
    builds: Builds, add: Any, fake_agent: FakeAgent
) -> None:
    add("s2", extra='agents = ["claude"]')
    add("s3", extra='agents = ["claude"]')

    assert run(scenarios=("s1", "s3")) == 0

    assert {cell.cell.scenario.id for cell in fake_agent.executed} == {"s1", "s3"}


def test_b_env_reaches_only_the_b_cells_environment_and_names_ref_b_in_the_report(
    bench_dirs: BenchDirs, builds: Builds, add: Any, fake_agent: FakeAgent
) -> None:
    fake_agent.script("s1", trace=trace(tool_calls=OK))

    run(b_env={"MCP_MEMORY_FEATURE_FIRST_BLOCK": "0"})

    (run_dir,) = (bench_dirs.state / "runs").iterdir()
    report = json.loads((run_dir / "report.json").read_text())
    assert (report["b"], report["b_env"]) == (
        ":worktree",
        {"MCP_MEMORY_FEATURE_FIRST_BLOCK": "0"},
    )
    assert {
        p.cell.variant.label: p.env.get("MCP_MEMORY_FEATURE_FIRST_BLOCK")
        for p in fake_agent.executed
    } == {"a": None, "b": "0"}


def test_a_finished_run_prunes_cached_builds_that_are_not_the_newest_of_a_ref(
    bench_dirs: BenchDirs, builds: Builds, add: Any, fake_agent: FakeAgent
) -> None:
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    stale = paths.variant_dir("stale-overlays-00000000")
    stale.mkdir(parents=True)

    run()

    assert not stale.exists()


def test_a_run_deletes_the_roots_of_dead_runs(
    builds: Builds, add: Any, fake_agent: FakeAgent, tmp_path: Path
) -> None:  # fmt: skip
    stale = tmp_path / "roots" / f"{paths.CELL_ROOT_PREFIX}4000001-x"
    stale.mkdir()
    fake_agent.script("s1", trace=trace(tool_calls=OK))

    assert run() == 0
    assert not stale.exists()


def test_terminating_a_run_interrupts_it_instead_of_killing_it(
    builds: Builds, add: Any, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    monkeypatch.setattr(
        command, "run_cells", lambda *args: signal.raise_signal(signal.SIGTERM)
    )

    with pytest.raises(KeyboardInterrupt):
        run()


def test_b_cells_are_reused_from_an_earlier_run_until_the_b_environment_changes(
    bench_dirs: BenchDirs,
    builds: Builds,
    add: Any,
    fake_agent: FakeAgent,
    run_ids: None,
) -> None:
    fake_agent.script("s1", trace=trace(tool_calls=OK))
    assert run() == 0
    fake_agent.executed.clear()

    assert run() == 0
    assert fake_agent.executed == []
    reused = [
        r for r in _results(bench_dirs, "20260101-000001-aaaa") if r["variant"] == "b"
    ]
    assert [r["reused_from"] for r in reused] == ["20260101-000000-aaaa"]

    assert run(b_env={"X": "1"}) == 0
    assert [p.cell.variant.label for p in fake_agent.executed] == ["b"]


@pytest.fixture
def sides(
    monkeypatch: pytest.MonkeyPatch, fake_agent: FakeAgent
) -> Callable[..., None]:
    def script(a: Any, b: Any) -> None:
        def execute(prepared: PreparedCell, *args: Any) -> Any:
            fake_agent.execute(prepared, *args)
            return a if prepared.cell.variant.label == "a" else b

        monkeypatch.setattr(process, "execute", execute)

    return script


def _repeats(fake_agent: FakeAgent, side: str) -> list[int]:
    return sorted(
        p.cell.repeat for p in fake_agent.executed if p.cell.variant.label == side
    )


def test_a_scenario_runs_once_per_side_and_again_up_to_the_cap_only_while_a_and_b_differ_on_pass(
    builds: Builds, add: Any, fake_agent: FakeAgent, sides: Callable[..., None]
) -> None:
    sides(trace(tool_calls=OK), trace(tool_calls=OK))
    assert run() == 0
    assert (_repeats(fake_agent, "a"), _repeats(fake_agent, "b")) == ([0], [0])
    fake_agent.executed.clear()

    sides(trace(tool_calls=OK), trace(tool_calls=()))

    run(reuse=False)
    assert (_repeats(fake_agent, "a"), _repeats(fake_agent, "b")) == (
        [0, 1, 2],
        [0, 1, 2],
    )
    fake_agent.executed.clear()

    run(reuse=False, max_repeats=2)
    assert (_repeats(fake_agent, "a"), _repeats(fake_agent, "b")) == ([0, 1], [0, 1])
    fake_agent.executed.clear()

    run(reuse=False, repeats=2)
    assert (_repeats(fake_agent, "a"), _repeats(fake_agent, "b")) == ([0, 1], [0, 1])


def test_a_cost_rise_over_the_gate_limit_adds_repeats_even_when_both_sides_pass(
    builds: Builds, add: Any, fake_agent: FakeAgent, sides: Callable[..., None]
) -> None:
    sides(trace(tool_calls=OK, cost_usd=1.0), trace(tool_calls=OK, cost_usd=2.0))

    run(reuse=False)

    assert _repeats(fake_agent, "b") == [0, 1, 2]


def test_reused_runs_count_toward_the_repeats_and_later_repeats_are_reused_too(
    builds: Builds, add: Any, fake_agent: FakeAgent, sides: Callable[..., None]
) -> None:
    sides(trace(tool_calls=OK), trace(tool_calls=()))
    run(repeats=2)
    fake_agent.executed.clear()

    run()

    assert sorted(p.cell.id for p in fake_agent.executed) == [
        "a-claude-s1-2",
        "b-claude-s1-2",
    ]


def test_a_side_that_only_has_startup_errors_gets_more_repeats_and_a_setup_error_stops_them(
    builds: Builds, add: Any, fake_agent: FakeAgent, sides: Callable[..., None]
) -> None:
    throttled = trace(
        exit_code=1, error="rate exceeded", tokens=Tokens(), tool_calls=()
    )
    sides(trace(tool_calls=OK), throttled)

    assert run(reuse=False) == 2

    assert _repeats(fake_agent, "a") == [0, 1, 2]
    fake_agent.executed.clear()
    sides(trace(tool_calls=OK), trace(exit_code=1, error="auth failed", tool_calls=OK))

    run(reuse=False, fail_fast=True, jobs=1)

    assert _repeats(fake_agent, "a") == [0]
    fake_agent.executed.clear()
    sides(throttled, throttled)

    run(reuse=False)

    assert {*_repeats(fake_agent, "a"), *_repeats(fake_agent, "b")} == {0}
