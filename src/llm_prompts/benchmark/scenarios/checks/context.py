"""What a check sees, and the helpers checks share."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from llm_prompts.benchmark.runner.sandbox import SandboxPolicy
from llm_prompts.benchmark.types import (
    CheckArg,
    CheckOutcome,
    MemoryEntity,
    ToolCall,
    Trace,
)

FAILED_ERROR_CHARS = 300


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
