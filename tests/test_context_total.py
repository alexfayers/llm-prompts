"""Tests for the context-total pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, ClassVar

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
    / "context-total.ts"
)
_HARNESS = Path(__file__).parent / "context_total_harness.mjs"
_BYTES_PER_TOKEN = 4


def _can_strip_types() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run(
        [node, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _can_strip_types(), reason="node with type stripping missing"
)


def _line(entry: dict[str, Any]) -> str:
    return json.dumps(entry, separators=(",", ":")) + "\n"


def _assistant(total: int, stop: str = "stop") -> str:
    return _line(
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "provider": "prov",
                "model": "mod",
                "stopReason": stop,
                "usage": {
                    "input": 1,
                    "output": 1,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "totalTokens": total,
                },
            },
        }
    )


def _tool_result(text: str) -> str:
    return _line({"type": "message", "message": {"role": "toolResult", "text": text}})


def _run(tmp_path: Path, steps: list[dict[str, Any]]) -> dict[str, Any]:
    config = tmp_path / "config.json"
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(exist_ok=True)
    config.write_text(
        json.dumps({"script": str(_SCRIPT), "agentDir": str(agent_dir), "steps": steps})
    )
    done = subprocess.run(
        ["node", str(_HARNESS), str(config)],
        check=True,
        capture_output=True,
        text=True,
    )
    output: dict[str, Any] = json.loads(done.stdout)
    assert "error" not in output, output["error"]
    results: dict[str, Any] = output["results"]
    return results


class TestScanTokens:
    """Tests for the live context estimate of a session file."""

    def test_usage_plus_trailing_estimate_ignoring_failed_replies_until_compaction(
        self, tmp_path: Path
    ) -> None:
        session = tmp_path / "session.jsonl"
        trailing = _tool_result("x" * 100)
        session.write_text(
            _assistant(1000)
            + _assistant(9000, "aborted")
            + _assistant(9000, "error")
            + trailing
        )
        compaction = _line({"type": "compaction", "summary": "s"})
        steps: list[dict[str, Any]] = [
            {"fn": "createScan", "args": ["owner"], "as": "scan"},
            {"fn": "readNew", "args": [{"$ref": "scan"}, str(session)]},
            {"fn": "scanTokens", "args": [{"$ref": "scan"}], "as": "before"},
            {"append": str(session), "text": compaction},
            {"fn": "readNew", "args": [{"$ref": "scan"}, str(session)]},
            {"fn": "scanTokens", "args": [{"$ref": "scan"}], "as": "compacted"},
            {"append": str(session), "text": _assistant(500)},
            {"fn": "readNew", "args": [{"$ref": "scan"}, str(session)]},
            {"fn": "scanTokens", "args": [{"$ref": "scan"}], "as": "after"},
        ]
        results = _run(tmp_path, steps)
        trailing_bytes = 2 * len(_assistant(9000, "error").strip()) + len(
            trailing.strip()
        )
        expected = 1000 + -(-trailing_bytes // _BYTES_PER_TOKEN)
        assert results["before"] == expected
        assert results["compacted"] is None
        assert results["after"] == 500


def _spawn(
    child: str,
    request: str,
    owner: str = "owner",
    tool: str = "delegate_agent",
    error: bool = False,
    sessions: str = "/sessions",
) -> str:
    return _line(
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "toolName": tool,
                "isError": error,
                "details": {
                    "ok": True,
                    "owner_session_id": owner,
                    "session_id": child,
                    "session_path": f"{sessions}/{child}.jsonl",
                    "agent": f"label-{child}",
                    "definition": "worker",
                    "request_id": request,
                },
            },
        }
    )


def _result(child: str, request: str, tokens: int, owner: str = "owner") -> str:
    return _line(
        {
            "type": "custom_message",
            "customType": "pi-herdsman-agent-result",
            "details": {
                "ownerSessionId": owner,
                "piSessionId": child,
                "requestId": request,
                "contextUsage": {
                    "tokens": tokens,
                    "contextWindow": 1000,
                    "percent": tokens / 10,
                },
            },
        }
    )


def _costed(cost: float, kind: str = "assistant", stop: str = "stop") -> str:
    usage = {
        "input": 10,
        "output": 5,
        "cacheRead": 3,
        "cacheWrite": 2,
        "cost": {"total": cost},
    }
    if kind == "usage":
        return _line({"type": "usage", "provider": "p", "model": "m", "usage": usage})
    return _line(
        {
            "type": "message",
            "message": {"role": kind, "stopReason": stop, "usage": usage},
        }
    )


class TestUsageTotals:
    """Tests for the cumulative tokens and cost of one session file."""

    def test_sums_every_usage_bearing_entry_including_failed_replies_and_tools(
        self, tmp_path: Path
    ) -> None:
        session = tmp_path / "session.jsonl"
        session.write_text(
            _costed(1.5)
            + _costed(0.25, stop="aborted")
            + _costed(0.125, kind="toolResult")
            + _costed(0.0625, kind="usage")
            + _tool_result("no usage here")
        )
        steps: list[dict[str, Any]] = [
            {"fn": "createScan", "args": ["owner"], "as": "scan"},
            {"fn": "readNew", "args": [{"$ref": "scan"}, str(session)]},
            {"fn": "scanUsage", "args": [{"$ref": "scan"}], "as": "usage"},
        ]
        usage = _run(tmp_path, steps)["usage"]
        assert usage["cost"] == 1.9375
        assert usage["tokens"] == 20


class TestReadNew:
    """Tests for reading only the new complete lines of a growing file."""

    def test_half_written_line_waits_and_shrunken_file_restarts(
        self, tmp_path: Path
    ) -> None:
        session = tmp_path / "session.jsonl"
        full = _assistant(5000)
        half = len(full) // 2
        session.write_text(_assistant(1000) + full[:half])
        read = [{"fn": "readNew", "args": [{"$ref": "scan"}, str(session)]}]
        steps: list[dict[str, Any]] = [
            {"fn": "createScan", "args": ["owner"], "as": "scan"},
            *read,
            {"fn": "scanTokens", "args": [{"$ref": "scan"}], "as": "half"},
            {"append": str(session), "text": full[half:]},
            *read,
            {"fn": "scanTokens", "args": [{"$ref": "scan"}], "as": "whole"},
            {"truncate": str(session), "text": _assistant(200)},
            *read,
            {"fn": "scanTokens", "args": [{"$ref": "scan"}], "as": "restarted"},
        ]
        results = _run(tmp_path, steps)
        assert [results[k] for k in ("half", "whole", "restarted")] == [1000, 5000, 200]


class TestChildren:
    """Tests for finding an owner's running and finished agents."""

    def test_spawn_runs_result_finishes_and_continue_runs_again(
        self, tmp_path: Path
    ) -> None:
        session = tmp_path / "session.jsonl"
        stages = [
            _spawn("c1", "r1")
            + _spawn("c2", "r2", tool="agent_delegate")
            + _spawn("c3", "r3", owner="other")
            + _spawn("c4", "r4", error=True),
            _result("c1", "r1", 400) + _result("c2", "stale", 50),
            _spawn("c1", "r5", tool="continue_agent"),
        ]
        steps: list[dict[str, Any]] = [
            {"fn": "createScan", "args": ["owner"], "as": "scan"}
        ]
        for index, text in enumerate(stages):
            steps += [
                {"append": str(session), "text": text},
                {"fn": "readNew", "args": [{"$ref": "scan"}, str(session)]},
                {"fn": "listChildren", "args": [{"$ref": "scan"}], "as": f"s{index}"},
            ]
        results = _run(tmp_path, steps)
        running = [
            {c["sessionId"]: c["done"] for c in results[f"s{index}"]}
            for index in range(len(stages))
        ]
        assert running == [
            {"c1": False, "c2": False},
            {"c1": True, "c2": False},
            {"c1": False, "c2": False},
        ]
        finished = results["s1"][0]
        assert finished["usage"] == {
            "tokens": 400,
            "contextWindow": 1000,
            "percent": 40,
        }
        assert finished["label"] == "label-c1"
        assert finished["definition"] == "worker"
        assert finished["sessionPath"] == "/sessions/c1.jsonl"


class TestSampleChildren:
    """Tests for walking the agent tree under a session."""

    def test_nested_agents_are_walked_with_cycles_and_unreadable_files_tolerated(
        self, tmp_path: Path
    ) -> None:
        sessions = str(tmp_path)
        lead = tmp_path / "lead.jsonl"
        lead.write_text(
            _spawn("c1", "r1", owner="lead", sessions=sessions)
            + _spawn("f1", "r2", owner="lead", sessions=sessions)
            + _result("f1", "r2", 400, owner="lead")
            + _spawn("n1", "r3", owner="lead", sessions=sessions)
        )
        (tmp_path / "c1.jsonl").write_text(
            _spawn("g1", "r4", owner="c1", sessions=sessions) + _assistant(2000)
        )
        (tmp_path / "g1.jsonl").write_text(
            _spawn("c1", "r5", owner="g1", sessions=sessions) + _assistant(300)
        )
        steps: list[dict[str, Any]] = [
            {"fn": "createScan", "args": ["lead"], "as": "root"},
            {"fn": "readNew", "args": [{"$ref": "root"}, str(lead)]},
            {
                "fn": "sampleChildren",
                "args": [
                    {"$ref": "root"},
                    {"$map": []},
                    {"windowOf": {"$windows": {"prov/mod": 10000}}},
                ],
                "as": "sample",
            },
        ]
        sample = _run(tmp_path, steps)["sample"]
        summary = [
            (
                n["sessionId"],
                n["depth"],
                n["state"],
                n["tokens"],
                n.get("contextWindow"),
            )
            for n in sample["nodes"]
        ]
        assert summary == [
            ("c1", 0, "live", 2000, 10000),
            ("g1", 1, "live", 300, 10000),
            ("f1", 0, "finished", 400, 1000),
            ("n1", 0, "live", None, None),
        ]
        assert sample["partial"] is False

    def test_running_agent_without_a_mailbox_is_lost_unless_mailboxes_are_unknown(
        self, tmp_path: Path
    ) -> None:
        sessions = str(tmp_path)
        lead = tmp_path / "lead.jsonl"
        lead.write_text(
            _spawn("c1", "r1", owner="lead", sessions=sessions)
            + _spawn("c2", "r2", owner="lead", sessions=sessions)
        )
        (tmp_path / "c1.jsonl").write_text(_assistant(700))
        (tmp_path / "c2.jsonl").write_text(_assistant(800))
        mailboxes = tmp_path / "agent" / "pi-herdsman" / "runtime" / "mailboxes-v5"
        (mailboxes / "aaa").mkdir(parents=True)
        (mailboxes / "aaa" / "state.json").write_text('{"piSessionId":"c2"}')
        (mailboxes / "bbb").mkdir()
        (mailboxes / "bbb" / "state.json").write_text("not json")
        (mailboxes / "ccc").mkdir()
        sample_steps: list[dict[str, Any]] = [
            {"fn": "createScan", "args": ["lead"], "as": "root"},
            {"fn": "readNew", "args": [{"$ref": "root"}, str(lead)]},
            {"fn": "readMailboxIds", "args": [str(tmp_path / "agent")], "as": "ids"},
            {"fn": "readMailboxIds", "args": [str(tmp_path / "none")], "as": "missing"},
        ]
        for name in ("ids", "missing"):
            sample_steps.append(
                {
                    "fn": "sampleChildren",
                    "args": [
                        {"$ref": "root"},
                        {"$map": []},
                        {"mailboxIds": {"$ref": name}},
                    ],
                    "as": f"sample_{name}",
                }
            )
        results = _run(tmp_path, sample_steps)
        assert results["ids"] == ["c2"]
        assert "missing" not in results
        states = {
            name: [
                (n["sessionId"], n["state"], n["tokens"])
                for n in results[f"sample_{name}"]["nodes"]
            ]
            for name in ("ids", "missing")
        }
        assert states == {
            "ids": [("c1", "lost", 700), ("c2", "live", 800)],
            "missing": [("c1", "live", 700), ("c2", "live", 800)],
        }

    def test_tree_usage_counts_lead_live_finished_and_nested_agents(
        self, tmp_path: Path
    ) -> None:
        sessions = str(tmp_path)
        lead = tmp_path / "lead.jsonl"
        lead.write_text(
            _costed(1.0)
            + _spawn("c1", "r1", owner="lead", sessions=sessions)
            + _spawn("f1", "r2", owner="lead", sessions=sessions)
            + _result("f1", "r2", 400, owner="lead")
        )
        (tmp_path / "c1.jsonl").write_text(
            _costed(2.0) + _spawn("g1", "r3", owner="c1", sessions=sessions)
        )
        (tmp_path / "g1.jsonl").write_text(_assistant(50) + _costed(4.0))
        (tmp_path / "f1.jsonl").write_text(
            _costed(0.5) + _spawn("h1", "r4", owner="f1", sessions=sessions)
        )
        (tmp_path / "h1.jsonl").write_text(_costed(0.25))
        steps: list[dict[str, Any]] = [
            {"fn": "createScan", "args": ["lead"], "as": "root"},
            {"fn": "readNew", "args": [{"$ref": "root"}, str(lead)]},
            {
                "fn": "sampleChildren",
                "args": [{"$ref": "root"}, {"$map": []}],
                "as": "sample",
            },
        ]
        sample = _run(tmp_path, steps)["sample"]
        assert sample["tree"] == {"tokens": 4 * 20 + 50, "cost": 7.75}
        assert sample["session"] == {"tokens": 20, "cost": 1.0}
        assert [node["sessionId"] for node in sample["nodes"]] == ["c1", "g1", "f1"]


def _node(
    label: str,
    depth: int,
    state: str,
    tokens: int | None,
    window: int | None,
    percent: float | None,
) -> dict[str, Any]:
    return {
        "sessionId": label,
        "label": label,
        "definition": "worker",
        "depth": depth,
        "state": state,
        "tokens": tokens,
        "contextWindow": window,
        "percent": percent,
    }


class TestFormatting:
    """Tests for the live total, the report and the footer."""

    def test_total_counts_only_live_sessions_and_marks_unknown_and_partial(
        self, tmp_path: Path
    ) -> None:
        lead = {"tokens": 1000, "contextWindow": 10000, "percent": 10}
        nodes = [
            _node("a", 0, "live", 2000, 10000, 20),
            _node("b", 1, "live", None, None, None),
            _node("c", 0, "finished", 400, 1000, 40),
            _node("d", 0, "lost", 700, None, None),
        ]
        sample = {
            "nodes": nodes,
            "partial": False,
            "session": {"tokens": 5000, "cost": 1.2},
            "tree": {"tokens": 9_000_000, "cost": 8.4},
        }
        steps: list[dict[str, Any]] = [
            {"fn": "formatReport", "args": [lead, sample], "as": "report"},
            {"fn": "formatFooter", "args": [sample], "as": "footer"},
            {
                "fn": "formatFooter",
                "args": [
                    {
                        "nodes": [],
                        "partial": True,
                        "session": {"tokens": 0, "cost": 0},
                        "tree": {"tokens": 0, "cost": 0},
                    },
                ],
                "as": "bare",
            },
        ]
        results = _run(tmp_path, steps)
        assert results["report"] == (
            "Live context: 3k+ across 3 sessions\n"
            "Running\n"
            "  lead  1k / 10k (10%)\n"
            "  a (worker)  2k / 10k (20%)\n"
            "    b (worker)  unknown\n"
            "Finished (last known)\n"
            "  c (worker)  400 / 1k (40%)\n"
            "  d (worker)  700 [lost]\n"
            "Tree cumulative: 9.0M tokens, $8.40\n"
            "Cumulative tokens and cost: /herdsman stats"
        )
        assert results["footer"] == "agents 2k+ \u00b7 tree 9.0M $1.20/$8.40"
        assert results["bare"] == "agents 0 \u00b7 tree 0 $0.00/$0.00 partial"


class TestPublishFooter:
    """Tests for handing the footer text to zentui or to a status line."""

    _SAMPLE: ClassVar[dict[str, Any]] = {
        "nodes": [],
        "partial": False,
        "session": {"tokens": 0, "cost": 1.2},
        "tree": {"tokens": 109_600_000, "cost": 8.4},
    }

    def _publish(
        self, tmp_path: Path, active: list[str]
    ) -> tuple[list[Any], list[Any]]:
        steps: list[dict[str, Any]] = [
            {
                "fn": "publishFooter",
                "args": [
                    {"$pi": "pi", "active": active},
                    {"$ui": "ui"},
                    self._SAMPLE,
                ],
            },
            {"emitted": "pi", "as": "emitted"},
            {"ui": "ui", "as": "status"},
        ]
        results = _run(tmp_path, steps)
        return results["emitted"], results["status"]

    def test_active_variables_are_published_and_the_status_line_cleared(
        self, tmp_path: Path
    ) -> None:
        keys = [
            "llm-prompts/context-total:ctx",
            "llm-prompts/context-total:cost",
        ]
        emitted, status = self._publish(tmp_path, keys)
        published = [
            (payload["key"], payload["text"])
            for event, payload in emitted
            if event == "zentui:variable"
        ]
        assert published == [
            (keys[0], "agents 0 \u00b7 tree 109.6M"),
            (keys[1], "$1.20/$8.40"),
        ]
        assert status == [["context-total", None]]

    def test_inactive_variables_fall_back_to_one_status_line(
        self, tmp_path: Path
    ) -> None:
        emitted, status = self._publish(tmp_path, [])
        assert not [e for e, _ in emitted if e == "zentui:variable"]
        assert status == [["context-total", "agents 0 \u00b7 tree 109.6M $1.20/$8.40"]]


class TestLeadTracker:
    """Tests for following the lead session's in-memory entries."""

    def test_reads_only_new_entries_and_restarts_on_new_session_or_shorter_list(
        self, tmp_path: Path
    ) -> None:
        def entry(owner: str, child: str) -> dict[str, Any]:
            spawned: dict[str, Any] = json.loads(
                _spawn(child, f"r-{child}", owner=owner)
            )
            return spawned

        def sync(
            name: str, session: str, entries: list[dict[str, Any]]
        ) -> list[dict[str, Any]]:
            return [
                {
                    "fn": "syncLead",
                    "args": [{"$ref": "tracker"}, session, entries],
                    "as": "scan",
                },
                {"fn": "listChildren", "args": [{"$ref": "scan"}], "as": name},
            ]

        first = entry("lead", "c1")
        steps: list[dict[str, Any]] = [
            {"fn": "createLeadTracker", "as": "tracker"},
            *sync("one", "lead", [first]),
            *sync("two", "lead", [first, entry("lead", "c2")]),
            *sync("other", "other", [entry("other", "c3")]),
            *sync("emptied", "other", []),
        ]
        results = _run(tmp_path, steps)
        ids = {
            k: [c["sessionId"] for c in results[k]]
            for k in ("one", "two", "other", "emptied")
        }
        assert ids == {
            "one": ["c1"],
            "two": ["c1", "c2"],
            "other": ["c3"],
            "emptied": [],
        }


class TestConfig:
    """Tests for the footer and interval settings file."""

    def test_defaults_clamped_interval_and_footer_rewrite_keeping_other_keys(
        self, tmp_path: Path
    ) -> None:
        file = tmp_path / "context-total.json"
        read = {"fn": "readConfig", "args": [str(file)]}
        steps: list[dict[str, Any]] = [
            {**read, "as": "missing"},
            {
                "truncate": str(file),
                "text": '{"footer":false,"intervalSeconds":1,"x":1}',
            },
            {**read, "as": "clamped"},
            {"fn": "writeFooterSetting", "args": [str(file), True]},
            {**read, "as": "enabled"},
        ]
        results = _run(tmp_path, steps)
        assert results["missing"] == {"footer": False, "intervalSeconds": 5}
        assert results["clamped"] == {"footer": False, "intervalSeconds": 2}
        assert results["enabled"] == {"footer": True, "intervalSeconds": 2}
        assert json.loads(file.read_text()) == {
            "footer": True,
            "intervalSeconds": 1,
            "x": 1,
        }
