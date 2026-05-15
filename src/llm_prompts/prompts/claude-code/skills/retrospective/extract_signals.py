"""Extract signals from recent Claude Code session transcripts."""

import argparse
import json
import os
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


def extract_retries(session: dict) -> list[dict]:
    """Find tool calls that were retried after failure."""
    retries = []
    messages = session["messages"]

    for msg in messages:
        if msg.get("type") != "assistant":
            continue
        content = msg.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue

        tool_uses = []
        tool_results = {}
        for block in content:
            if block.get("type") == "tool_use":
                tool_uses.append(block)
            elif block.get("type") == "tool_result":
                tool_results[block.get("tool_use_id", "")] = block

        bash_runs: list[dict] = []
        for tu in tool_uses:
            if tu.get("name") != "Bash":
                continue
            cmd = tu.get("input", {}).get("command", "")
            lead = cmd.split("&&")[0].split("|")[0].strip().split()[0] if cmd else ""
            result = tool_results.get(tu.get("id", ""), {})
            result_content = result.get("content", "")
            if isinstance(result_content, list):
                result_content = str(result_content)
            is_error = "error" in str(result_content).lower()[:500] or "Error" in str(
                result_content
            )[:500]
            bash_runs.append({"command": cmd[:200], "lead": lead, "error": is_error})

        consecutive_fails: list[dict] = []
        for run in bash_runs:
            if run["error"]:
                consecutive_fails.append(run)
            else:
                if len(consecutive_fails) >= 2 and run["lead"] == consecutive_fails[0]["lead"]:
                    retries.append({
                        "session_id": session["session_id"],
                        "project": session["project"],
                        "command_pattern": consecutive_fails[0]["lead"],
                        "attempts": len(consecutive_fails) + 1,
                        "first_command": consecutive_fails[0]["command"],
                    })
                consecutive_fails = []

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
