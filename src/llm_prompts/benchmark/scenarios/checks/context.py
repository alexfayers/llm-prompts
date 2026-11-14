"""What a check sees, and the helpers checks share."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from llm_prompts.benchmark.cell.env import check_env, host_env, with_venv
from llm_prompts.benchmark.runner.sandbox import SandboxPolicy, wrap
from llm_prompts.benchmark.types import (
    CheckArg,
    CheckOutcome,
    MemoryEntity,
    ToolCall,
    Trace,
)

FAILED_ERROR_CHARS = 300
GIT_TIMEOUT_S = 60


@dataclass(frozen=True)
class CheckContext:
    trace: Trace
    workspace: Path
    memory_before: tuple[MemoryEntity, ...]
    memory_after: tuple[MemoryEntity, ...]
    judge: str = "auto"
    base_trace: Trace | None = None
    ask: str = ""
    venv: Path | None = None
    sandbox: SandboxPolicy | None = None
    env: Mapping[str, str] | None = None


CheckFn = Callable[[Mapping[str, CheckArg], CheckContext], CheckOutcome]


def args_text(call: ToolCall) -> str:
    return "\n".join(
        value if isinstance(value, str) else json.dumps(value)
        for value in call.args.values()
    )


def matching(
    ctx: CheckContext,
    name: str,
    args_regex: str | None,
    text_regex: str | None = None,
    by: str | None = None,
) -> Iterator[int]:
    for index, call in enumerate(ctx.trace.tool_calls):
        if (
            re.fullmatch(name, call.name)
            and (by is None or call.subagent == (by == "subagent"))
            and (args_regex is None or re.search(args_regex, args_text(call)))
            and (text_regex is None or re.search(text_regex, call.text))
        ):
            yield index


def optional(args: Mapping[str, CheckArg], key: str) -> str | None:
    return str(args[key]) if key in args else None


def in_cell(
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


def git(ctx: CheckContext, *args: str) -> str:
    """Run git in the workspace and return its stripped output, raising CalledProcessError on failure."""
    argv = ["git", *args]
    result = in_cell(ctx, argv, GIT_TIMEOUT_S)
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode, argv, result.stdout, result.stderr
        )
    return result.stdout.strip()


def first_commit(ctx: CheckContext) -> str:
    """Return the first commit of the workspace repo, which holds the files as the cell started."""
    return git(ctx, "rev-list", "--max-parents=0", "HEAD").splitlines()[0]
