"""End-to-end test running the real benchmark command with real claude and pi."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from llm_prompts.benchmark import paths
from llm_prompts.benchmark.cell.audit import live_memory

_ENABLE_VAR = "LLM_PROMPTS_BENCH_E2E"
_SCENARIO = "recall-retry-policy"
_AGENTS = ("claude", "pi")
_LIVE_FILES = (
    Path(".claude.json"),
    Path(".claude") / "settings.json",
    Path(".pi") / "agent" / "settings.json",
    Path(".pi") / "agent" / "mcp.json",
    Path(".config") / "llm-prompts" / "installed.json",
    Path(".config") / "llm-prompts" / "config.toml",
)
_DEMO_ENTITIES = (
    "SELECT e.id, e.name, e.status, o.content FROM entities e"
    " LEFT JOIN observations o ON o.entity_id = e.id"
    " WHERE e.name LIKE '%demo%' OR e.name = 'knowledge/demo-retry-policy'"
    " ORDER BY e.id, o.id"
)


def _file_hashes() -> dict[Path, str | None]:
    home = Path.home()
    return {
        path: hashlib.sha256((home / path).read_bytes()).hexdigest()
        if (home / path).exists()
        else None
        for path in _LIVE_FILES
    }


def _demo_rows() -> list[tuple[object, ...]]:
    db_path, _ = live_memory()
    if not db_path.exists():
        return []
    with closing(
        sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    ) as db:
        return db.execute(_DEMO_ENTITIES).fetchall()


def _run_ids() -> set[str]:
    return {p.name for p in paths.runs_dir().glob("*") if p.is_dir()}


@pytest.mark.real_io
@pytest.mark.skipif(
    os.environ.get(_ENABLE_VAR) != "1", reason=f"set {_ENABLE_VAR}=1 to run"
)
def test_real_benchmark_run_leaves_live_state_untouched() -> None:
    hashes_before = _file_hashes()
    rows_before = _demo_rows()
    runs_before = _run_ids()

    proc = subprocess.run(
        [
            "llm-prompts",
            "benchmark",
            "--level",
            "light",
            "--scenario",
            _SCENARIO,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode in (0, 1), proc.stderr
    new_runs = _run_ids() - runs_before
    assert len(new_runs) == 1
    run_dir = paths.run_dir(new_runs.pop())

    rows = [
        json.loads(line)
        for line in (run_dir / "results.jsonl").read_text().splitlines()
    ]
    assert sorted((row["variant"], row["agent"]) for row in rows) == [
        (variant, agent) for variant in ("a", "b") for agent in _AGENTS
    ]
    assert all(row["error"] is None for row in rows)
    for row in rows:
        assert row["tokens"]["input"] + row["tokens"]["output"] > 0
        assert row["tool_calls"] > 0
        assert row["model"]
    for agent in _AGENTS:
        assert any(
            row["memory"]["memory_calls"] >= 1 for row in rows if row["agent"] == agent
        )

    report = (run_dir / "report.md").read_text()
    assert report.startswith("# Benchmark ")
    for agent in _AGENTS:
        assert re.search(rf"^\| {_SCENARIO} \| {agent} \|", report, re.MULTILINE)

    assert _file_hashes() == hashes_before
    assert _demo_rows() == rows_before
