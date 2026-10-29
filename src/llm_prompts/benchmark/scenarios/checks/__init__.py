"""Check kinds and their evaluation."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping, Sequence

from llm_prompts.benchmark.cell.env import check_env, host_env, with_venv
from llm_prompts.benchmark.cell.memory import (
    MEMORY_TOOL_PREFIX,
    READ_TOOLS,
    observation_keys,
)
from llm_prompts.benchmark.runner.sandbox import wrap
from llm_prompts.benchmark.scenarios.checks.context import (
    FAILED_ERROR_CHARS,
    CheckContext,
    CheckFn,
    args_text,
    matching,
    optional,
)
from llm_prompts.benchmark.scenarios.checks.judge import judge
from llm_prompts.benchmark.types import (
    CheckArg,
    CheckOutcome,
    CheckSpec,
    ToolCall,
    Trace,
)


def _run(spec: CheckSpec, ctx: CheckContext) -> CheckOutcome:
    try:
        return CHECKS[spec.kind](spec.args, ctx)
    except Exception as exc:
        return CheckOutcome(
            spec.kind, False, f"{spec.kind} raised {type(exc).__name__}: {exc}"
        )


def evaluate(specs: Sequence[CheckSpec], ctx: CheckContext) -> list[CheckOutcome]:
    """Run every check in ``specs`` against ``ctx`` and return their outcomes."""
    return [_run(spec, ctx) for spec in specs]


BASH = r"(?i)bash"
TEST_RUN = r"\bpytest\b"
COMMAND_EXITED = r"(?i)\bexit(ed)?\b.{0,20}\bcode \d+"
TEST_SUCCESS = r"\b\d+ passed\b"
TEST_FAILURE = r"\b\d+ (failed|errors?)\b|\bno tests ran\b"
GIT_TIMEOUT_S = 60
COMMAND_TIMEOUT_S = 180


def tool_called(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if a tool call matches the name and arguments (made by the ``lead`` or a ``subagent`` when ``by`` is given), and comes before any ``before`` call."""
    name = str(args["name"])
    first = next(
        matching(ctx, name, optional(args, "args_regex"), by=optional(args, "by")),
        None,
    )
    if first is None:
        return CheckOutcome("tool_called", False, f"no call matches {name!r}")
    before = optional(args, "before")
    if before is not None:
        limit = next(matching(ctx, before, optional(args, "before_args_regex")), None)
        if limit is not None and first >= limit:
            return CheckOutcome("tool_called", False, f"{name!r} came after {before!r}")
    return CheckOutcome("tool_called", True, f"call matches {name!r}")


def max_time(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if the cell's wall time is within ``seconds``."""
    seconds = int(str(args["seconds"]))
    wall = ctx.trace.wall_s
    return CheckOutcome(
        "max_time", wall <= seconds, f"took {wall:.0f}s, limit {seconds}s"
    )


def memory_recalled(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if the named entities were injected into the context or read through memory."""
    entities = args["entities"]
    names = entities if isinstance(entities, tuple) else (str(entities),)
    lines = ctx.trace.injected_context.splitlines()
    injected = all(
        any(line.startswith(f"- {name} (") for line in lines) for name in names
    )
    read_tools = "|".join(sorted(READ_TOOLS))
    call_args: dict[str, CheckArg] = {
        "name": f"{re.escape(MEMORY_TOOL_PREFIX)}({read_tools})"
    }
    if "before" in args:
        call_args["before"] = args["before"]
    called = tool_called(call_args, ctx).passed
    paths = [path for path, hit in (("injected", injected), ("called", called)) if hit]
    detail = " and ".join(paths) if paths else "not injected and no memory read call"
    return CheckOutcome("memory_recalled", bool(paths), detail)


def not_called(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if no tool call matches the name, arguments, result text and ``by`` (``lead`` or ``subagent``)."""
    name = str(args["name"])
    matches = matching(
        ctx,
        name,
        optional(args, "args_regex"),
        optional(args, "text_regex"),
        optional(args, "by"),
    )
    if next(matches, None) is None:
        return CheckOutcome("not_called", True, f"no call matches {name!r}")
    return CheckOutcome("not_called", False, f"call matches {name!r}")


def _hook_blocked(call: ToolCall) -> bool:
    return not call.ok and re.search(COMMAND_EXITED, call.text) is None


def _test_runs(trace: Trace) -> list[ToolCall]:
    return [
        call
        for call in trace.tool_calls
        if re.fullmatch(BASH, call.name)
        and re.search(TEST_RUN, args_text(call))
        and not _hook_blocked(call)
    ]


def _test_run_failed(call: ToolCall) -> bool:
    return not call.ok or re.search(TEST_FAILURE, call.text) is not None


def failed_test_runs(trace: Trace) -> int:
    """Return the number of test runs in ``trace`` that were rejected or reported a failure."""
    return sum(map(_test_run_failed, _test_runs(trace)))


def tests_passed(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if the last test run in the session reported passing tests."""
    runs = _test_runs(ctx.trace)
    if not runs:
        return CheckOutcome("tests_passed", False, "no test run")
    last = runs[-1]
    passed = not _test_run_failed(last) and re.search(TEST_SUCCESS, last.text)
    return CheckOutcome(
        "tests_passed",
        bool(passed),
        f"last of {len(runs)} test runs {'passed' if passed else 'did not pass'}",
    )


def file_regex(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if a workspace file matches the regex."""
    path, regex = str(args["path"]), str(args["regex"])
    root = ctx.workspace.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return CheckOutcome("file_regex", False, f"no file {path!r} in the workspace")
    found = re.search(regex, target.read_text(), re.MULTILINE) is not None
    return CheckOutcome(
        "file_regex", found, f"{path!r} {'matches' if found else 'lacks'} {regex!r}"
    )


def memory_written(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if enough entities matching the filters have a new observation."""
    name_regex = optional(args, "name_regex")
    entity_type = optional(args, "entity_type")
    regex = optional(args, "regex")
    relation = optional(args, "relation")
    target_regex = optional(args, "target_regex")
    wanted = int(str(args.get("min_entities", 1)))
    known = observation_keys(ctx.memory_before)
    matched = [
        entity.name
        for entity in ctx.memory_after
        if (name_regex is None or re.search(name_regex, entity.name))
        and (entity_type is None or entity.entity_type == entity_type)
        and (
            (relation is None and target_regex is None)
            or any(
                (relation is None or kind == relation)
                and (target_regex is None or re.search(target_regex, target))
                for target, kind in entity.relations
            )
        )
        and any(
            (entity.name, text) not in known
            and (regex is None or re.search(regex, text))
            for text in entity.observations
        )
    ]
    return CheckOutcome(
        "memory_written",
        len(matched) >= wanted,
        f"{len(matched)} of {wanted} entities with a new observation: {matched}",
    )


def memory_absent(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if no new observation on a matching entity matches the regex.

    With ``include_existing``, observations already present before the run count too.
    """
    name_regex, regex = str(args["name_regex"]), str(args["regex"])
    known = (
        set() if args.get("include_existing") else observation_keys(ctx.memory_before)
    )
    for entity in ctx.memory_after:
        if re.search(name_regex, entity.name):
            for text in entity.observations:
                if (entity.name, text) not in known and re.search(regex, text):
                    return CheckOutcome(
                        "memory_absent", False, f"{entity.name!r} has {text!r}"
                    )
    return CheckOutcome("memory_absent", True, f"no new observation matches {regex!r}")


def _in_cell(
    ctx: CheckContext, argv: Sequence[str], timeout: int
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` in the workspace inside the cell's OS sandbox, with only the variables a check needs."""
    base = ctx.env or (with_venv(host_env(), ctx.venv) if ctx.venv else host_env())
    return subprocess.run(
        wrap(argv, ctx.sandbox) if ctx.sandbox else list(argv),
        cwd=ctx.workspace,
        env=check_env(base),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _git(ctx: CheckContext, *args: str) -> str:
    argv = ["git", *args]
    result = _in_cell(ctx, argv, GIT_TIMEOUT_S)
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode, argv, result.stdout, result.stderr
        )
    return result.stdout.strip()


def git_state(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if ``branch`` has ``commits`` commits since ``since``, its tip message matches ``message_regex`` and ``remote`` still has the branch at ``since``."""
    branch, since = str(args["branch"]), str(args["since"])
    problems: list[str] = []
    if "commits" in args:
        count = int(_git(ctx, "rev-list", "--count", f"{since}..{branch}"))
        if count != int(str(args["commits"])):
            problems.append(f"{count} commits on {branch} since {since}")
    if "message_regex" in args:
        message = _git(ctx, "log", "-1", "--format=%B", branch)
        if not re.search(str(args["message_regex"]), message):
            problems.append(f"tip message {message!r} lacks {args['message_regex']!r}")
    if "remote" in args:
        remote = str(args["remote"])
        pushed = _git(ctx, "ls-remote", remote, f"refs/heads/{branch}").split()[:1]
        if pushed != [_git(ctx, "rev-parse", since)]:
            problems.append(f"remote {remote} moved {branch} off {since}")
    return CheckOutcome(
        "git_state", not problems, "; ".join(problems) or f"{branch} as expected"
    )


def command_exit(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if the shell ``command`` run in the workspace exits with ``exit`` (default 0)."""
    wanted = int(str(args.get("exit", 0)))
    result = _in_cell(ctx, ["sh", "-c", str(args["command"])], COMMAND_TIMEOUT_S)
    detail = f"exited {result.returncode}, wanted {wanted}"
    if result.returncode != wanted:
        detail += f"\n{(result.stdout + result.stderr)[-FAILED_ERROR_CHARS:]}"
    return CheckOutcome("command_exit", result.returncode == wanted, detail)


def _paths(args: Mapping[str, CheckArg]) -> list[str]:
    paths = args["path"]
    return list(paths) if isinstance(paths, tuple) else [str(paths)]


def _first_commit(ctx: CheckContext) -> str:
    return _git(ctx, "rev-list", "--max-parents=0", "HEAD").splitlines()[0]


def _changed_paths(args: Mapping[str, CheckArg], ctx: CheckContext) -> list[str]:
    return _git(
        ctx, "diff", "--name-only", _first_commit(ctx), "--", *_paths(args)
    ).splitlines()


def files_unchanged(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if the ``path`` pathspecs in the workspace still match the first commit."""
    changed = _changed_paths(args, ctx)
    return CheckOutcome(
        "files_unchanged",
        not changed,
        f"changed: {changed}" if changed else "unchanged since the first commit",
    )


def files_changed(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if any of the ``path`` pathspecs in the workspace differs from the first commit."""
    changed = _changed_paths(args, ctx)
    return CheckOutcome(
        "files_changed",
        bool(changed),
        f"changed: {changed}" if changed else "unchanged since the first commit",
    )


def byte_size(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if the workspace file is no larger than in the first commit."""
    path = str(args["path"])
    before = int(_git(ctx, "cat-file", "-s", f"{_first_commit(ctx)}:{path}"))
    now = (ctx.workspace / path).stat().st_size
    return CheckOutcome(
        "byte_size", now <= before, f"{path!r} is {now} bytes, was {before}"
    )


CHECKS: dict[str, CheckFn] = {
    "judge": judge,
    "tool_called": tool_called,
    "max_time": max_time,
    "memory_recalled": memory_recalled,
    "not_called": not_called,
    "tests_passed": tests_passed,
    "file_regex": file_regex,
    "memory_written": memory_written,
    "memory_absent": memory_absent,
    "git_state": git_state,
    "command_exit": command_exit,
    "files_unchanged": files_unchanged,
    "files_changed": files_changed,
    "byte_size": byte_size,
}
