"""The judge check: a minimal agent rules whether the evidence meets a rubric."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from typing import cast

from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.cell.memory import observation_keys
from llm_prompts.benchmark.scenarios.checks.context import (
    FAILED_ERROR_CHARS,
    CheckContext,
    args_text,
    first_commit,
    git,
    matching,
    optional,
)
from llm_prompts.benchmark.types import Agent, CheckArg, CheckOutcome, Trace

JUDGE_TIMEOUT_S = 300
EVIDENCE_CHARS = 2000
RUBRIC_DETAIL_CHARS = 60
VERDICT_LINE = re.compile(r"\W*(PASS|FAIL)\W*", re.IGNORECASE)
JUDGE_SYSTEM = (
    "Reply with PASS if the evidence meets the rubric, else FAIL, alone on the first line. "
    "Then give the reason on the following lines, naming each rubric clause that fails."
)


def _evidence(args: Mapping[str, CheckArg], ctx: CheckContext) -> str:
    """Return the workspace files, matching tool call args, rejected tool calls or final text, each truncated, and every new memory observation, each truncated, to judge."""
    paths = args.get("path", ())
    files = (
        [paths]
        if isinstance(paths, str)
        else list(paths)
        if isinstance(paths, tuple)
        else []
    )
    parts = []
    for path in files:
        if (ctx.workspace / path).is_file():
            current = (ctx.workspace / path).read_text(errors="replace")
            original = _original(ctx, path)
            if original is not None and original != current.strip():
                parts.append(f"{path} (original):\n{original}")
            parts.append(f"{path}:\n{current}")
    if "name" in args:
        parts += [
            f"{ctx.trace.tool_calls[index].name}:\n{args_text(ctx.trace.tool_calls[index])}"
            for index in matching(ctx, str(args["name"]), optional(args, "args_regex"))
        ]
    parts = [_capped(part) for part in parts]
    if args.get("memory"):
        added = observation_keys(ctx.memory_after) - observation_keys(ctx.memory_before)
        parts.append(_capped(f"User's ask:\n{ctx.ask}"))
        parts.append(
            "\n".join(sorted(_capped(f"{name}: {text}") for name, text in added))
        )
    if args.get("failed"):
        parts.append(_capped(_failed_calls(ctx)))
    if not (files or "name" in args or args.get("memory") or args.get("failed")):
        parts = [_capped(ctx.trace.final_text)]
    return "\n\n".join(parts)


def _original(ctx: CheckContext, path: str) -> str | None:
    """Return the file as the cell started, or None if the workspace has no such file in its first commit."""
    try:
        return git(ctx, "show", f"{first_commit(ctx)}:{path}")
    except (subprocess.CalledProcessError, IndexError):
        return None


def _capped(text: str) -> str:
    return text[:EVIDENCE_CHARS]


def _failed_calls(ctx: CheckContext) -> str:
    """Return the rejected tool calls with their args and error text, labelled by session when a follow-up has a base trace."""
    if ctx.base_trace is None:
        return _failed_in(ctx.trace, "Rejected tool calls")
    return "\n\n".join(
        (
            _failed_in(ctx.base_trace, "Rejected tool calls (base session)"),
            _failed_in(ctx.trace, "Rejected tool calls (this session)"),
        )
    )


def _failed_in(trace: Trace, heading: str) -> str:
    failed = [
        f"REJECTED (not saved): {call.name} args={args_text(call)} error={call.error[:FAILED_ERROR_CHARS]}"
        for call in trace.tool_calls
        if not call.ok
    ]
    return f"{heading}:\n" + "\n\n".join(failed) if failed else f"{heading}: none"


class JudgeMissing(RuntimeError):
    """The chosen judge harness is not on PATH."""


def judge_harness(choice: str) -> Agent:
    """Return the judge command for ``choice``: pi when on PATH for ``auto``, else claude."""
    if choice == "auto":
        return "pi" if shutil.which("pi") else "claude"
    return cast(Agent, choice)


def require_judge(choice: str) -> None:
    """Raise JudgeMissing when the harness chosen for the judge is not on PATH."""
    harness = judge_harness(choice)
    if not shutil.which(harness):
        raise JudgeMissing(f"The judge harness {harness!r} is not on PATH.")


def judge(args: Mapping[str, CheckArg], ctx: CheckContext) -> CheckOutcome:
    """Pass if a minimal judge rules the evidence meets the rubric."""
    rubric = args.get("rubric")
    if not isinstance(rubric, str):
        return CheckOutcome("judge", False, "missing rubric")
    harness = judge_harness(ctx.judge)
    agent = AGENTS[harness]
    model = args.get("model", agent.judge_model)
    with tempfile.TemporaryDirectory() as cwd:
        result = subprocess.run(
            [
                *agent.judge_argv(JUDGE_SYSTEM),
                "--model",
                str(model),
            ],
            input=f"Rubric:\n{rubric}\n\nEvidence:\n{_evidence(args, ctx)}\n",
            env=agent.judge_env(str(model), JUDGE_TIMEOUT_S),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=JUDGE_TIMEOUT_S,
        )
    reply = agent.parse(((0.0, line) for line in result.stdout.splitlines()), 0.0)
    tokens = reply.tokens.total
    if result.returncode != 0:
        return CheckOutcome(
            "judge",
            False,
            f"judge exited {result.returncode}: {result.stderr.strip()[:500]}",
            tokens,
        )
    first, _, reason = reply.final_text.strip().partition("\n")
    match = VERDICT_LINE.fullmatch(first.strip())
    if match:
        verdict = match[1].upper()
        detail = f"judge said {verdict} on: {rubric[:RUBRIC_DETAIL_CHARS]}"
        if reason := reason.strip():
            detail += f"\n{reason}"
        return CheckOutcome("judge", verdict == "PASS", detail, tokens)
    return CheckOutcome(
        "judge", False, f"unparseable judge reply: {reply.final_text}", tokens
    )
