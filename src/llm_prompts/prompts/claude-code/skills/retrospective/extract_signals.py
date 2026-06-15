"""Extract signals from recent Claude Code session transcripts."""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

CORRECTION_PATTERNS = re.compile(
    r"(?i)(?:^|\n)\s*(?:"
    r"no[,.\s!]|nope|wrong|stop|wait|don'?t|do not|not that|"
    r"I said|I meant|that'?s not|actually[,.]|"
    r"WOAH|NO[!.]"
    r")",
)
INTERRUPTION_MARKER = "[Request interrupted by user]"


def find_recent_sessions(n: int) -> list[Path]:
    """Find the N most recently modified JSONL transcript files."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return []
    jsonl_files = list(projects_dir.glob("*/*.jsonl"))
    jsonl_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonl_files[:n]


def parse_session(path: Path) -> dict:
    """Parse a single session JSONL file and extract signals."""
    messages: list[dict] = []
    title = path.stem[:12]
    project = path.parent.name

    for line in path.open():
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        msg_type = obj.get("type")
        if msg_type == "ai-title":
            title = obj.get("aiTitle", title)
        elif msg_type in ("user", "assistant"):
            messages.append(obj)

    return {
        "path": str(path),
        "session_id": path.stem,
        "project": project,
        "title": title,
        "messages": messages,
    }


def extract_corrections(session: dict) -> list[dict]:
    """Find user messages that correct or redirect the agent."""
    corrections = []
    messages = session["messages"]

    for i, msg in enumerate(messages):
        if msg.get("type") != "user":
            continue
        content = msg.get("message", {}).get("content", "")
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if b.get("type") == "text"
            )
        if not content:
            continue
        if INTERRUPTION_MARKER in content:
            corrections.append({
                "session_id": session["session_id"],
                "project": session["project"],
                "title": session["title"],
                "user_said": content[:300],
                "type": "interruption",
            })
            continue
        if CORRECTION_PATTERNS.search(content[:200]):
            context = ""
            if i > 0:
                prev = messages[i - 1]
                prev_content = prev.get("message", {}).get("content", [])
                if isinstance(prev_content, list):
                    for block in prev_content:
                        if block.get("type") == "text":
                            context = block.get("text", "")[:200]
                            break
            corrections.append({
                "session_id": session["session_id"],
                "project": session["project"],
                "title": session["title"],
                "user_said": content[:300],
                "context_before": context,
                "type": "correction",
            })
    return corrections


def _bash_lead(cmd: str) -> str:
    """Return the meaningful leading command token of a shell string.

    Skips a leading `cd <path> &&` so failures are attributed to the real
    command rather than the directory change.
    """
    if not cmd:
        return ""
    segments = re.split(r"&&|;|\n", cmd)
    for seg in segments:
        tokens = seg.split("|")[0].strip().split()
        if tokens and tokens[0] != "cd":
            return tokens[0]
    first = segments[0].strip().split()
    return first[0] if first else ""


def _result_is_error(result: dict) -> bool:
    """Determine whether a tool_result block represents a failure."""
    if result.get("is_error"):
        return True
    content = result.get("content", "")
    if isinstance(content, list):
        content = " ".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
    head = str(content)[:500]
    return "<tool_use_error>" in head or "Exit code 1" in head


def extract_retries(session: dict) -> list[dict]:
    """Find tool calls that were retried after failure across the session.

    tool_result blocks live in separate user messages keyed by tool_use_id,
    so results are collected session-wide before walking the ordered tool_use
    sequence to detect runs of consecutive same-tool failures.
    """
    messages = session["messages"]

    results_by_id: dict[str, dict] = {}
    for msg in messages:
        content = msg.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_result":
                results_by_id[block.get("tool_use_id", "")] = block

    runs: list[dict] = []
    for msg in messages:
        if msg.get("type") != "assistant":
            continue
        content = msg.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            if name == "Bash":
                cmd = block.get("input", {}).get("command", "")
                key = _bash_lead(cmd)
            else:
                cmd = ""
                key = name
            if not key:
                continue
            result = results_by_id.get(block.get("id", ""), {})
            runs.append({
                "key": key,
                "command": cmd[:200],
                "error": _result_is_error(result),
            })

    retries: list[dict] = []
    fails: list[dict] = []
    for run in runs:
        if fails and (not run["error"] or run["key"] != fails[0]["key"]):
            if len(fails) >= 2:
                retries.append({
                    "session_id": session["session_id"],
                    "project": session["project"],
                    "command_pattern": fails[0]["key"],
                    "attempts": len(fails),
                    "first_command": fails[0]["command"],
                    "recovered": not run["error"] and run["key"] == fails[0]["key"],
                })
            fails = []
        if run["error"]:
            fails.append(run)
    if len(fails) >= 2:
        retries.append({
            "session_id": session["session_id"],
            "project": session["project"],
            "command_pattern": fails[0]["key"],
            "attempts": len(fails),
            "first_command": fails[0]["command"],
            "recovered": False,
        })

    return retries


def extract_tool_patterns(session: dict) -> Counter:
    """Count tool usage across the session."""
    counter: Counter = Counter()
    for msg in session["messages"]:
        if msg.get("type") != "assistant":
            continue
        content = msg.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                counter[block.get("name", "unknown")] += 1
    return counter


def compute_session_meta(session: dict) -> dict:
    """Compute session metadata: turns, duration."""
    messages = session["messages"]
    user_turns = sum(1 for m in messages if m.get("type") == "user")

    timestamps = []
    for m in messages:
        ts = m.get("timestamp")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                pass

    duration_minutes = 0
    if len(timestamps) >= 2:
        delta = timestamps[-1] - timestamps[0]
        duration_minutes = int(delta.total_seconds() / 60)

    return {
        "session_id": session["session_id"],
        "project": session["project"],
        "title": session["title"],
        "turns": user_turns,
        "duration_minutes": duration_minutes,
    }


def main() -> None:
    """Run the signal extraction pipeline."""
    parser = argparse.ArgumentParser(description="Extract signals from Claude Code transcripts")
    parser.add_argument("--sessions", type=int, default=10, help="Number of recent sessions to analyse")
    args = parser.parse_args()

    paths = find_recent_sessions(args.sessions)
    if not paths:
        json.dump({"error": "No transcripts found", "sessions_analysed": 0}, sys.stdout)
        return

    all_corrections: list[dict] = []
    all_retries: list[dict] = []
    long_sessions: list[dict] = []
    tool_totals: Counter = Counter()

    for path in paths:
        session = parse_session(path)
        all_corrections.extend(extract_corrections(session))
        all_retries.extend(extract_retries(session))
        tool_totals += extract_tool_patterns(session)
        meta = compute_session_meta(session)
        if meta["turns"] >= 50 or meta["duration_minutes"] >= 60:
            long_sessions.append(meta)

    result = {
        "sessions_analysed": len(paths),
        "corrections": all_corrections,
        "retries": all_retries,
        "long_sessions": long_sessions,
        "tool_patterns": dict(tool_totals.most_common(30)),
    }

    json.dump(result, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
