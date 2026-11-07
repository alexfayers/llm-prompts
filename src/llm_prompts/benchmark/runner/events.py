"""Shared parsing helpers for agent event streams.

`CallLog` keeps a memory call only when it failed, and the result text of every other call. The memory server logs the rest.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from llm_prompts.benchmark.types import ToolCall

MCP_PREFIX = "mcp__"
MEMORY_MCP_PREFIX = f"{MCP_PREFIX}memory__"


def mcp_name(raw: str, builtins: Mapping[str, str] | None = None) -> str:
    """Return `server.tool` for an MCP tool, else the builtin's display name."""
    if not raw.startswith(MCP_PREFIX):
        return (builtins or {}).get(raw, raw)
    server, _, tool = raw.removeprefix(MCP_PREFIX).partition("__")
    return f"{server}.{tool}"


def parse_line(line: str) -> dict[str, Any] | None:
    """Return a streamed line as a JSON object, or None when it is not one."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def count(usage: object, key: str) -> int:
    """Return an integer usage field, or 0 when absent or not an integer."""
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if isinstance(value, int) else 0


def result_texts(content: object) -> list[str]:
    """Return the text blocks of a tool result."""
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
    return []


def result_failed(is_error: object, content: object) -> bool:
    """Whether a memory call failed, as flagged or as an `error` result."""
    if is_error:
        return True
    for text in result_texts(content):
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "error" in parsed:
            return True
    return False


@dataclass
class CallLog:
    """Tool calls of one run, without the successful memory calls."""

    builtins: Mapping[str, str] | None = None
    _calls: dict[str, ToolCall] = field(default_factory=dict)
    _memory: dict[str, ToolCall] = field(default_factory=dict)

    def start(
        self, call_id: str, raw: str, args: object, at: float, subagent: bool = False
    ) -> None:
        """Record a started call, holding a memory call until it ends unless a subagent made it."""
        held = raw.startswith(MEMORY_MCP_PREFIX) and not subagent
        pending = self._memory if held else self._calls
        pending[call_id] = ToolCall(
            mcp_name(raw, self.builtins),
            args if isinstance(args, dict) else {},
            False,
            at,
            subagent=subagent,
        )

    def end(self, call_id: str, is_error: object, content: object) -> None:
        """Settle a call, keeping a memory call only when it failed and a successful call's result text."""
        text = "\n".join(result_texts(content))
        if call_id in self._memory:
            if result_failed(is_error, content):
                self._calls[call_id] = replace(self._memory[call_id], error=text)
        elif call_id in self._calls:
            self._calls[call_id] = replace(
                self._calls[call_id],
                ok=not is_error,
                error=text if is_error else "",
                output="" if is_error else text,
            )

    def calls(self) -> tuple[ToolCall, ...]:
        """Return the kept calls in the order they were recorded."""
        return tuple(self._calls.values())


@dataclass
class ContextMeter:
    """Context size of the first and the largest model call."""

    start: int = 0
    peak: int = 0

    def add(self, tokens: int) -> None:
        """Record the context size of one model call."""
        self.peak = max(self.peak, tokens)
        self.start = self.start or tokens
