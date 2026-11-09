import json
from collections.abc import Callable
from typing import Any

import pytest

from llm_prompts.benchmark.agents.claude import ClaudeAdapter
from llm_prompts.benchmark.agents.pi import PiAdapter

Lines = list[tuple[float, str]]


def _claude(call_id: str, name: str, failed: Any = "") -> list[dict[str, Any]]:
    use = {"type": "tool_use", "id": call_id, "name": name, "input": {}}
    out = {"type": "tool_result", "tool_use_id": call_id, "content": failed}
    return [
        {"type": "assistant", "message": {"content": [use]}},
        {"type": "user", "message": {"content": [out]}},
    ]


def _pi(call_id: str, name: str, failed: Any = "") -> list[dict[str, Any]]:
    start = {"type": "tool_execution_start", "toolCallId": call_id, "toolName": name}
    return [
        start,
        {**start, "type": "tool_execution_end", "result": {"content": failed}},
    ]


def _lines(events: list[dict[str, Any]]) -> Lines:
    return [(float(i), json.dumps(e)) for i, e in enumerate(events, start=1)]


@pytest.mark.parametrize(
    ("runner", "events"),
    [(ClaudeAdapter(), _claude), (PiAdapter(), _pi)],
    ids=["claude", "pi"],
)
def test_failed_memory_calls_are_kept_and_successful_ones_dropped(
    runner: ClaudeAdapter | PiAdapter, events: Callable[..., list[dict[str, Any]]]
) -> None:
    error: Any = [{"type": "text", "text": json.dumps({"error": "bad"})}]
    ok: Any = [{"type": "text", "text": "2 passed"}, {"type": "text", "text": "ok"}]
    stream: list[dict[str, Any]] = [
        *events("1", "mcp__memory__create_entities", error),
        *events("2", "mcp__memory__read_graph", ok),
        *events("3", "mcp__other__lookup", ok),
    ]

    lines = [*_lines(stream), (99.0, "not json"), (100.0, "[]")]

    calls = runner.parse(lines, wall_s=0.0).tool_calls

    assert [c.name for c in calls] == ["memory.create_entities", "other.lookup"]
    assert calls[0].error == json.dumps({"error": "bad"})
    assert (calls[1].output, calls[1].error) == ("2 passed\nok", "")


@pytest.mark.parametrize(
    ("runner", "reply", "other"),
    [
        (ClaudeAdapter(), {"type": "assistant"}, {"type": "system"}),
        (
            PiAdapter(),
            {"type": "message_end", "message": {"role": "assistant"}},
            {"type": "message_end", "message": {"role": "user"}},
        ),
    ],
    ids=["claude", "pi"],
)
def test_replied_is_true_only_for_an_assistant_reply(
    runner: ClaudeAdapter | PiAdapter, reply: dict[str, Any], other: dict[str, Any]
) -> None:
    assert runner.replied(json.dumps(reply))
    assert not runner.replied(json.dumps(other))
    assert not runner.replied("not json")


@pytest.mark.parametrize(
    ("runner", "events"),
    [(ClaudeAdapter(), _claude), (PiAdapter(), _pi)],
    ids=["claude", "pi"],
)
@pytest.mark.parametrize("name", ["bash", "mcp__memory__create_entities"])
def test_a_failed_call_keeps_its_error_text(
    runner: ClaudeAdapter | PiAdapter,
    events: Callable[..., list[dict[str, Any]]],
    name: str,
) -> None:
    text: Any = [{"type": "text", "text": "RuntimeError: unknown environment"}]
    stream = events("1", name, text)
    stream[-1] = {**stream[-1], "isError": True}
    if isinstance(runner, ClaudeAdapter):
        stream[-1]["message"]["content"][0]["is_error"] = True

    (call,) = runner.parse(_lines(stream), wall_s=0.0).tool_calls

    assert (call.ok, call.error) == (False, "RuntimeError: unknown environment")


def test_pi_builtin_tools_are_renamed() -> None:
    names = ("bash", "read", "edit", "write", "grep", "find")

    trace = PiAdapter().parse(_lines([e for n in names for e in _pi(n, n)]), 0.0)

    assert [c.name for c in trace.tool_calls] == [
        "Bash", "Read", "Edit", "Write", "Grep", "Glob",
    ]  # fmt: skip


def test_claude_result_hooks_and_turns_become_trace_fields() -> None:
    hook = {"type": "system", "subtype": "hook_response", "hook_event": "SessionStart"}
    usage = {"input_tokens": 1, "output_tokens": 2}
    stream: list[dict[str, Any]] = [
        {"type": "system", "subtype": "init", "model": "m"},
        {**hook, "output": "note"},
        {"type": "assistant", "message": {"id": "a", "usage": {"input_tokens": 7}}},
        {
            "type": "result",
            "result": "done",
            "usage": usage,
            "total_cost_usd": 0.5,
            "is_error": True,
            "stop_reason": "max_turns",
        },
    ]

    trace = ClaudeAdapter().parse(_lines(stream), wall_s=0.0)

    assert (trace.model, trace.final_text, trace.cost_usd) == ("m", "done", 0.5)
    assert (trace.tokens.input, trace.tokens.output, trace.exit_code) == (1, 2, 1)
    assert (trace.injected_context, trace.turns, trace.context) == ("note", 1, 7)
    assert trace.error == "max_turns: done"


def test_pi_messages_become_trace_fields() -> None:
    usage = {"input": 4, "output": 2, "cost": {"total": 0.5}}
    hook = {"role": "custom", "customType": "cline-hooks", "content": "note"}
    reply: dict[str, Any] = {
        "role": "assistant",
        "model": "m",
        "stopReason": "stop",
        "usage": usage,
    }
    reply["content"] = [{"type": "text", "text": "done"}]
    stream: list[dict[str, Any]] = [
        {"type": "message_end", "message": m} for m in (hook, reply)
    ]

    trace = PiAdapter().parse(_lines([*stream, {"type": "agent_settled"}]), wall_s=0.0)

    assert (trace.model, trace.final_text, trace.cost_usd) == ("m", "done", 0.5)
    assert (trace.tokens.input, trace.turns, trace.exit_code) == (4, 1, 0)
    assert trace.injected_context == "note"


def test_claude_marks_subagent_calls_and_leaves_them_out_of_the_lead_trace_fields() -> (
    None
):
    stream: list[dict[str, Any]] = [
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "usage": {"input_tokens": 100},
                "content": [
                    {"type": "tool_use", "id": "lead-1", "name": "Agent", "input": {}}
                ],
            },
        },
        {
            "type": "assistant",
            "parent_tool_use_id": "lead-1",
            "message": {
                "id": "m2",
                "usage": {"input_tokens": 900},
                "content": [
                    {
                        "type": "tool_use",
                        "id": "sub-1",
                        "name": "mcp__memory__create_entities",
                        "input": {},
                    }
                ],
            },
        },
        {
            "type": "user",
            "parent_tool_use_id": "lead-1",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "sub-1", "content": "ok"}
                ]
            },
        },
        *_claude("lead-2", "Bash"),
    ]

    trace = ClaudeAdapter().parse(_lines(stream), wall_s=0.0)

    assert [(c.name, c.subagent) for c in trace.tool_calls] == [
        ("Agent", False),
        ("memory.create_entities", True),
        ("Bash", False),
    ]
    assert (trace.context, trace.turns) == (100, 2)
