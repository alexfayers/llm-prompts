import json
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest
from conftest import FakeSubprocess

from benchmark.conftest import pi_settings_path
from benchmark.traces import make_trace
from llm_prompts.benchmark.scenarios.checks import CHECKS, evaluate, failed_test_runs
from llm_prompts.benchmark.scenarios.checks.context import CheckContext
from llm_prompts.benchmark.scenarios.checks.judge import JudgeMissing, require_judge
from llm_prompts.benchmark.types import (
    CheckArg,
    CheckOutcome,
    CheckSpec,
    MemoryEntity,
    ToolCall,
)


def run(
    kind: str,
    args: Mapping[str, CheckArg],
    calls: tuple[ToolCall, ...] = (),
    *,
    text: str = "",
    ws: Path = Path("ws"),
    before: tuple[MemoryEntity, ...] = (),
    after: tuple[MemoryEntity, ...] = (),
    base_calls: tuple[ToolCall, ...] | None = None,
    ask: str = "",
) -> CheckOutcome:
    trace = make_trace(tool_calls=calls, final_text=text)
    base = None if base_calls is None else make_trace(tool_calls=base_calls)
    ctx = CheckContext(trace, ws, before, after, base_trace=base, ask=ask)
    (outcome,) = evaluate([CheckSpec(kind, args)], ctx)
    return outcome


def claude_reply(text: str) -> str:
    usage = {"input_tokens": 400, "output_tokens": 5}
    return json.dumps({"type": "result", "result": text, "usage": usage})


def pi_reply(text: str) -> str:
    message = {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "usage": {"input": 70, "output": 3},
    }
    return json.dumps({"type": "message_end", "message": message})


def c(name: str, **args: str) -> ToolCall:
    return ToolCall(name, args, True)


def sub(name: str) -> ToolCall:
    return ToolCall(name, {}, True, subagent=True)


def test_a_raising_check_fails_without_stopping_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(CHECKS, "boom", lambda args, ctx: 1 / 0)
    ctx = CheckContext(make_trace(final_text="x"), Path("ws"), (), ())

    raised, ok = evaluate(
        [CheckSpec("boom", {}), CheckSpec("not_called", {"name": "x"})], ctx
    )

    assert (raised.passed, ok.passed) == (False, True)
    assert "ZeroDivisionError" in raised.detail


EXITED = "2 failed\n\nCommand exited with code 1"


def pytest_call(output: str, ok: bool = True) -> ToolCall:
    return ToolCall("Bash", {"command": "DEMO_ENV=test pytest -q"}, ok, output=output)


@pytest.mark.parametrize(
    ("kind", "args", "calls", "expected"),
    [
        ("tool_called", {"name": "Edit"}, (), False),
        (
            "tool_called",
            {"name": "Read", "before": "Edit"},
            (c("Edit"), c("Read")),
            False,
        ),
        ("tool_called", {"name": "Read", "before": "Edit"}, (c("Read"),), True),
        (
            "not_called",
            {"name": "Bash", "args_regex": "push"},
            (ToolCall("Bash", {"command": "git push"}, False),),
            False,
        ),
        ("not_called", {"name": "Edit"}, (c("Other"),), True),
        (
            "not_called",
            {"name": "(?i)bash", "text_regex": "RuntimeError: unknown"},
            (ToolCall("bash", {}, False, error="RuntimeError: unknown env"),),
            False,
        ),
        (
            "not_called",
            {"name": "(?i)bash", "text_regex": "RuntimeError: unknown"},
            (ToolCall("Bash", {}, True, output="RuntimeError: unknown env"),),
            False,
        ),
        (
            "not_called",
            {"name": "(?i)bash", "text_regex": "RuntimeError: unknown"},
            (ToolCall("Bash", {}, True, output="all fine"),),
            True,
        ),
        ("tool_called", {"name": "Edit", "by": "lead"}, (sub("Edit"),), False),
        ("tool_called", {"name": "Edit", "by": "subagent"}, (sub("Edit"),), True),
        ("not_called", {"name": "Edit", "by": "subagent"}, (c("Edit"),), True),
        ("not_called", {"name": "Edit", "by": "subagent"}, (sub("Edit"),), False),
        ("tests_passed", {}, (), False),
        ("tests_passed", {}, (pytest_call("2 passed"),), True),
        (
            "tests_passed",
            {},
            (pytest_call("2 passed"), pytest_call("1 failed, 1 passed")),
            False,
        ),
        ("tests_passed", {}, (pytest_call("2 errors"), pytest_call("2 passed")), True),
        ("tests_passed", {}, (pytest_call(EXITED, ok=False),), False),
        ("tests_passed", {}, (pytest_call("pytest"),), False),
        (
            "memory_recalled",
            {"entities": ("k/demo",)},
            (c("memory.search_nodes"),),
            True,
        ),
        ("memory_recalled", {"entities": "k/demo"}, (), False),
    ],
)
def test_trace_checks(
    kind: str, args: Mapping[str, CheckArg], calls: tuple[ToolCall, ...], expected: bool
) -> None:
    assert run(kind, args, calls).passed is expected


def test_failed_test_runs_counts_rejected_runs_and_runs_that_report_a_failure_but_not_hook_blocked_ones() -> (
    None
):
    calls = (
        pytest_call(EXITED, ok=False),
        pytest_call("blocked by a hook", ok=False),
        pytest_call("1 failed, 2 passed"),
        pytest_call("3 passed"),
        ToolCall("Bash", {"command": "ls"}, False),
    )

    assert failed_test_runs(make_trace(tool_calls=calls)) == 2


def test_output_file_and_memory_checks(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("ttl = 2 ** n\n")
    new = (
        MemoryEntity("task/other", "task", ("is 30",)),
        MemoryEntity("task/ttl", "task", ("is 30",)),
    )
    args = {"name_regex": "ttl", "regex": "30"}

    assert run("file_regex", {"path": "f.py", "regex": r"2\s*\*\*"}, ws=tmp_path).passed
    assert not run("file_regex", {"path": "../x", "regex": "x"}, ws=tmp_path).passed
    assert run("memory_written", args, after=new).passed
    assert not run("memory_absent", args, after=new).passed


def test_memory_absent_ignores_observations_already_in_memory_before() -> None:
    old = MemoryEntity("project/demo", "project", ("seeded note",))
    new = MemoryEntity("project/demo", "project", ("seeded note", "added note"))
    args = {"name_regex": "^project/", "regex": "."}

    assert run("memory_absent", args, before=(old,), after=(old,)).passed
    assert not run("memory_absent", args, before=(old,), after=(new,)).passed


def test_memory_absent_can_count_existing_observations() -> None:
    old = MemoryEntity("task/ttl", "task", ("is 60 seconds",))
    args: dict[str, CheckArg] = {
        "name_regex": "ttl",
        "regex": "60",
        "include_existing": True,
    }

    assert not run("memory_absent", args, before=(old,), after=(old,)).passed


def test_memory_written_relation_filter() -> None:
    linked = MemoryEntity("task/a", "task", ("x",), (("feature/demo/f", "implements"),))
    wrong_type = MemoryEntity(
        "task/b", "task", ("x",), (("feature/demo/f", "part-of"),)
    )
    wrong_target = MemoryEntity(
        "task/c", "task", ("x",), (("project/demo", "implements"),)
    )
    args = {"relation": "implements", "target_regex": "^feature/demo/"}

    assert run("memory_written", args, after=(linked,)).passed
    assert not run("memory_written", args, after=(wrong_type, wrong_target)).passed


def test_memory_written_min_entities() -> None:
    task = MemoryEntity("task/a", "task", ("x",))
    other = MemoryEntity("task/b", "task", ("x",))
    old = MemoryEntity("task/c", "task", ("x",))
    args: dict[str, CheckArg] = {"name_regex": "^task/", "min_entities": 2}

    assert run("memory_written", args, before=(old,), after=(task, other, old)).passed
    assert not run("memory_written", args, before=(old,), after=(task, old)).passed


@pytest.mark.parametrize(
    ("stdout", "code", "passed"),
    [
        ("PASS\n", 0, True),
        ("FAIL\n", 0, False),
        ("PASS because", 0, False),
        ("", 1, False),
    ],
)
def test_judge_verdict_and_call(
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
    stdout: str,
    code: int,
    passed: bool,
) -> None:
    (tmp_path / "f.py").write_text("x" * 5000)
    fake_subprocess.on_match(
        lambda argv: argv[0] == "claude",
        stdout=claude_reply(stdout),
        returncode=code,
    )
    calls = (c("Bash", command="git commit -m 'feat: x'"), c("Bash", command="ls"))
    args = {
        "rubric": "Mentions limit",
        "path": "f.py",
        "name": "Bash",
        "args_regex": "commit",
    }

    outcome = run("judge", {**args, "model": "x"}, calls, ws=tmp_path)

    assert (outcome.passed, outcome.tokens) == (passed, 405)

    ((argv, kwargs),) = (
        call for call in fake_subprocess.calls if call[0][0] == "claude"
    )
    assert argv[argv.index("--model") + 1] == "x"
    assert argv[argv.index("--tools") + 1] == ""
    assert kwargs["input"].count("x") < 2100 + 100
    assert "git commit" in kwargs["input"]
    assert "ls" not in kwargs["input"].split("Bash:")[1]
    assert not run("judge", {}).passed


def test_judge_detail_keeps_the_full_reason_after_the_verdict_line(
    fake_subprocess: FakeSubprocess,
) -> None:
    reason = "Clause 2 fails: " + "the tests never assert the raised error. " * 5
    fake_subprocess.on_match(
        lambda argv: argv[0] == "claude", stdout=claude_reply(f"fail\n{reason}\n")
    )

    outcome = run("judge", {"rubric": "r"}, text="x")

    assert not outcome.passed
    assert outcome.detail == f"judge said FAIL on: r\n{reason.strip()}"


def test_judge_reads_a_markdown_wrapped_verdict(
    fake_subprocess: FakeSubprocess,
) -> None:
    fake_subprocess.on_match(
        lambda argv: argv[0] == "claude",
        stdout=claude_reply("**FAIL**\n\n- **Task entity** missing\n"),
    )

    outcome = run("judge", {"rubric": "r"}, text="x")

    assert not outcome.passed
    assert outcome.detail == "judge said FAIL on: r\n- **Task entity** missing"


@pytest.mark.usefixtures("judge_passes")
def test_judge_memory_option_shows_the_ask_and_only_the_observations_added_in_the_cell(
    fake_subprocess: FakeSubprocess,
) -> None:
    before = (MemoryEntity("task/a", "task", ("old note",)),)
    after = (MemoryEntity("task/a", "task", ("old note", "new note")),)

    assert run(
        "judge",
        {"rubric": "r", "memory": 1},
        text="chat",
        before=before,
        after=after,
        ask="Add a tag filter",
    ).passed

    ((_, kwargs),) = fake_subprocess.calls
    assert "User's ask:\nAdd a tag filter\n\ntask/a: new note" in kwargs["input"]
    assert "old note" not in kwargs["input"]
    assert "chat" not in kwargs["input"]


@pytest.mark.usefixtures("judge_passes")
def test_judge_memory_option_shows_every_new_observation_not_just_the_first_2000_chars(
    fake_subprocess: FakeSubprocess,
) -> None:
    notes = tuple(f"note {number} " + "x" * 1500 for number in range(3))
    after = (MemoryEntity("task/a", "task", notes),)

    assert run("judge", {"rubric": "r", "memory": 1}, after=after).passed

    ((_, kwargs),) = fake_subprocess.calls
    assert all(note in kwargs["input"] for note in notes)


@pytest.mark.usefixtures("judge_passes")
@pytest.mark.parametrize(
    ("calls", "expected", "absent"),
    [
        (
            (
                ToolCall("Bash", {"command": "pytest"}, False, error="unknown env"),
                ToolCall("Bash", {"command": "echo fine"}, True),
            ),
            "Rejected tool calls:\nREJECTED (not saved): Bash args=pytest error=unknown env",
            "echo fine",
        ),
        (
            (ToolCall("Bash", {"command": "echo fine"}, True),),
            "Rejected tool calls: none",
            "echo fine",
        ),
    ],
    ids=["failed", "none"],
)
def test_judge_failed_option_lists_the_failed_tool_calls(
    fake_subprocess: FakeSubprocess,
    calls: tuple[ToolCall, ...],
    expected: str,
    absent: str,
) -> None:

    assert run("judge", {"rubric": "r", "failed": True}, calls, text="chat").passed

    ((_, kwargs),) = fake_subprocess.calls
    assert expected in kwargs["input"]
    assert absent not in kwargs["input"].partition("Evidence:")[2]
    assert "chat" not in kwargs["input"]


@pytest.mark.usefixtures("judge_passes")
def test_judge_failed_option_labels_the_base_session_failures_of_a_follow_up(
    fake_subprocess: FakeSubprocess,
) -> None:
    base_calls = (ToolCall("Bash", {"command": "pytest"}, False, error="unknown env"),)

    assert run("judge", {"rubric": "r", "failed": True}, base_calls=base_calls).passed

    ((_, kwargs),) = fake_subprocess.calls
    assert (
        "Rejected tool calls (base session):\nREJECTED (not saved): Bash args=pytest error=unknown env\n\n"
        "Rejected tool calls (this session): none"
    ) in kwargs["input"]


def test_judge_runs_in_the_host_env_and_reports_stderr(
    fake_subprocess: FakeSubprocess, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOST_MARK", "1")
    monkeypatch.setenv("HERDR_PANE", "p")
    monkeypatch.setenv("GIT_DIR", "d")
    monkeypatch.setenv("PI_SUBAGENT_CHILD", "1")
    fake_subprocess.on_match(
        lambda argv: argv[0] == "claude", returncode=1, stderr="  no shim \n"
    )

    outcome = run("judge", {"rubric": "r"}, text="x")

    ((_, kwargs),) = fake_subprocess.calls
    assert kwargs["env"]["HOST_MARK"] == "1"
    dropped = ("HERDR_", "GIT_", "PI_SUBAGENT_")
    assert not {k for k in kwargs["env"] if k.startswith(dropped)}
    assert outcome.detail == "judge exited 1: no shim"


@pytest.fixture
def pi_judge(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
) -> FakeSubprocess:
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: f"/bin/{name}")
    monkeypatch.delenv("AWS_REGION", raising=False)
    (isolated_home / ".claude").mkdir()
    (isolated_home / ".claude" / "settings.json").write_text(
        '{"env": {"AWS_REGION": "eu-west-1"}}'
    )
    fake_subprocess.on_match(lambda argv: argv[1:2] == ["-p"], stdout=pi_reply("PASS"))
    return fake_subprocess


def test_judge_uses_pi_when_it_is_on_path(pi_judge: FakeSubprocess) -> None:
    pi_judge.on_match(lambda argv: "--list-models" in argv, stdout="")

    outcome = run("judge", {"rubric": "r"}, text="the answer")

    assert (outcome.passed, outcome.tokens) == (True, 73)
    ((argv, kwargs),) = [c for c in pi_judge.calls if "-p" in c[0]]
    assert argv[0] == "pi"
    assert argv[argv.index("--model") + 1] == "test-model"
    assert "the answer" in kwargs["input"]
    assert "AWS_REGION" not in kwargs["env"]


def test_judge_needs_a_pi_default_model(pi_judge: FakeSubprocess) -> None:
    pi_settings_path().unlink()

    with pytest.raises(JudgeMissing, match="defaultModel"):
        require_judge("pi")


def test_judge_sets_the_region_only_for_a_bedrock_model(
    pi_judge: FakeSubprocess,
) -> None:
    pi_judge.on_match(
        lambda argv: "--list-models" in argv,
        stdout="provider  model\namazon-bedrock  haiku\n",
    )

    assert run("judge", {"rubric": "r"}, text="x").passed

    (kwargs,) = [c[1] for c in pi_judge.calls if "-p" in c[0]]
    assert kwargs["env"]["AWS_REGION"] == "eu-west-1"


@pytest.mark.parametrize(("wall_s", "passed"), [(59.0, True), (61.0, False)])
def test_max_time_fails_a_cell_that_ran_too_long(wall_s: float, passed: bool) -> None:
    ctx = CheckContext(make_trace(wall_s=wall_s), Path("ws"), (), ())

    (outcome,) = evaluate([CheckSpec("max_time", {"seconds": 60})], ctx)

    assert outcome.passed is passed


@pytest.mark.usefixtures("judge_passes")
def test_judge_defaults_to_the_final_text(fake_subprocess: FakeSubprocess) -> None:

    assert run("judge", {"rubric": "r"}, text="the answer").passed

    ((argv, kwargs),) = fake_subprocess.calls
    assert argv[argv.index("--model") + 1] == "haiku"
    assert "the answer" in kwargs["input"]
