"""Claude PreToolUse hook that blocks denied Bash commands."""

from __future__ import annotations

import json
import re
import sys

_GIT_VALUE_OPTION = r"(?:-[Cc]|--(?:git-dir|work-tree|namespace|exec-path|config-env))"

DENIED: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\blaunchctl\b"), "launchctl is blocked in the benchmark."),
    (re.compile(r"\bsystemctl\b"), "systemctl is blocked in the benchmark."),
    (
        re.compile(r"\b(?:pkill|killall|kill)\b.*mcp-memory"),
        "Killing mcp-memory is blocked in the benchmark.",
    ),
    (
        re.compile(
            rf"\bgit\b(?:\s+(?:{_GIT_VALUE_OPTION}\s+\S+|(?!{_GIT_VALUE_OPTION}\s)-\S+))*\s+push\b"
        ),
        "git push is blocked in the benchmark.",
    ),
    (
        re.compile(r"\bmcp-memory\s+(?:restart|setup-service|stop|start)\b"),
        "mcp-memory restart, setup-service, stop and start are blocked in the benchmark.",
    ),
    (
        re.compile(r"\bllm-prompts\s+(?:update|setup|setup-service|uninstall)\b"),
        "llm-prompts update, setup, setup-service and uninstall are blocked in the benchmark.",
    ),
    (
        re.compile(r"\bllm-prompts\s+install\b(?![^;&|\n]*--root)"),
        "llm-prompts install without --root is blocked in the benchmark.",
    ),
)

BLOCKED_EXIT_CODE = 2


def _verdict(raw: str) -> str | None:
    event = json.loads(raw)
    if event.get("tool_name") != "Bash":
        return None
    command = event["tool_input"]["command"]
    return next((reason for pattern, reason in DENIED if pattern.search(command)), None)


def main() -> int:
    """Read a hook payload from stdin and return the exit code."""
    try:
        reason = _verdict(sys.stdin.read())
    except Exception as error:
        reason = f"guard failed: {error}"
    if reason is None:
        return 0
    print(f"Blocked by benchmark guard: {reason}", file=sys.stderr)
    return BLOCKED_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
