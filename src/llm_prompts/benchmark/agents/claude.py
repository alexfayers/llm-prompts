"""The claude agent: its command line, output parsing and benchmark setup."""

from __future__ import annotations

import json
import shlex
import sys
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path

from llm_prompts.benchmark.agents.adapter import GUARD_ARGV, VariantBuildError
from llm_prompts.benchmark.agents.files import (
    copy_login,
    merge_json,
    read_json,
    run_steps,
    write_json,
)
from llm_prompts.benchmark.cell.audit import live_markers
from llm_prompts.benchmark.cell.env import host_env
from llm_prompts.benchmark.paths import live_home
from llm_prompts.benchmark.runner.events import (
    CallLog,
    ContextMeter,
    count,
    mcp_name,
    parse_line,
)
from llm_prompts.benchmark.types import (
    JsonValue,
    PreparedCell,
    Scenario,
    Session,
    Tokens,
    Trace,
)

DELEGATION_TOOLS = "Agent,Task"


def _session_uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def _blocks(event: Mapping[str, object]) -> list[Mapping[str, object]]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _hook_context(output: str) -> str:
    try:
        parsed = json.loads(output)
        return str(parsed["hookSpecificOutput"]["additionalContext"])
    except (ValueError, KeyError, TypeError):
        return output


MEMORY_PERMISSION = "mcp__memory__*"
CLAUDE_SETTINGS_KEYS = ("awsCredentialExport", "awsAuthRefresh", "apiKeyHelper")
CLAUDE_ENV_PREFIXES = ("AWS_", "ANTHROPIC_")
CLAUDE_ENV_NAMES = ("CLAUDE_CODE_USE_BEDROCK",)


def _claude_json(live: Path, home: Path) -> Path | None:
    account = read_json(live / ".claude.json", strict=False).get("oauthAccount")
    if account is None:
        return None
    return merge_json(home / ".claude" / ".claude.json", {"oauthAccount": account})


def _points_into_live(value: JsonValue) -> bool:
    return isinstance(value, str) and any(marker in value for marker in live_markers())


def _claude_settings(live: Path, home: Path) -> Path | None:
    source = read_json(live / ".claude" / "settings.json", strict=False)
    updates: dict[str, JsonValue] = {}
    for key in CLAUDE_SETTINGS_KEYS:
        if key not in source:
            continue
        if _points_into_live(source[key]):
            print(f"benchmark: skipped settings key {key}", file=sys.stderr)
            continue
        updates[key] = source[key]
    env = source.get("env")
    auth_env = (
        {
            key: value
            for key, value in env.items()
            if key.startswith(CLAUDE_ENV_PREFIXES) or key in CLAUDE_ENV_NAMES
        }
        if isinstance(env, dict)
        else {}
    )
    if auth_env:
        updates["env"] = auth_env
    if not updates:
        return None
    return merge_json(home / ".claude" / "settings.json", updates, nested=("env",))


class ClaudeAdapter:
    template_name = "claude-code"
    default_model = "sonnet"
    judge_model = "haiku"
    cumulative_cost = True
    delegation = True
    shared_dirs: tuple[Path, ...] = ()
    git_packages: Path | None = None

    def point_memory(self, home: Path, url: str) -> None:
        config_path = home / ".claude" / ".claude.json"
        config = read_json(config_path)
        config.setdefault("mcpServers", {})["memory"] = {"type": "http", "url": url}
        settings_path = home / ".claude" / "settings.json"
        settings = read_json(settings_path)
        allow = settings.setdefault("permissions", {}).setdefault("allow", [])
        if MEMORY_PERMISSION not in allow:
            allow.append(MEMORY_PERMISSION)
        write_json(config_path, config)
        write_json(settings_path, settings)

    def install_guard(self, template_dir: Path) -> None:
        settings_path = template_dir / ".claude" / "settings.json"
        try:
            settings = read_json(settings_path)
        except (ValueError, TypeError) as error:
            raise VariantBuildError(str(settings_path), str(error)) from error
        command = shlex.join(GUARD_ARGV)
        entries = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
        if not any(
            hook.get("command") == command
            for entry in entries
            for hook in entry.get("hooks", [])
        ):
            entries.append(
                {"matcher": "Bash", "hooks": [{"type": "command", "command": command}]}
            )
        write_json(settings_path, settings)

    def copy_logins(self, home: Path) -> tuple[Path, ...]:
        live = live_home()
        return run_steps(
            (
                lambda: copy_login(
                    live / ".claude" / ".credentials.json",
                    home / ".claude" / ".credentials.json",
                ),
                lambda: _claude_json(live, home),
                lambda: _claude_settings(live, home),
            )
        )

    def judge_argv(self, system_prompt: str) -> list[str]:
        return [
            "claude", "-p", "--output-format", "json", "--no-session-persistence", "--tools", "",
            "--setting-sources", "", "--disable-slash-commands", "--strict-mcp-config",
            "--system-prompt", system_prompt,
        ]  # fmt: skip

    def judge_env(self, model: str, timeout_s: int) -> dict[str, str]:
        return host_env()

    def command(
        self,
        prepared: PreparedCell,
        scenario: Scenario,
        model: str,
        session: Session | None = None,
    ) -> list[str]:
        """Return the claude argv for the scenario, saving the session when one is given."""
        if session is None:
            session_args = ["--no-session-persistence"]
        elif session.fork:
            session_args = ["--resume", _session_uuid(session.fork), "--fork-session"]
        else:
            session_args = ["--session-id", _session_uuid(session.id)]
        return [
            "claude",
            "-p",
            scenario.prompt,
            *([] if scenario.delegation else ["--disallowedTools", DELEGATION_TOOLS]),
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            model,
            "--dangerously-skip-permissions",
            *session_args,
        ]

    def replied(self, line: str) -> bool:
        event = parse_line(line)
        return event is not None and event.get("type") == "assistant"

    def tool_started(self, line: str) -> str | None:
        event = parse_line(line)
        if event is None or event.get("type") != "assistant":
            return None
        names = [
            mcp_name(str(block.get("name", "")))
            for block in _blocks(event)
            if block.get("type") == "tool_use"
        ]
        return names[-1] if names else None

    def parse(self, lines: Iterable[tuple[float, str]], wall_s: float) -> Trace:
        log = CallLog()
        meter = ContextMeter()
        model = ""
        final_text = ""
        tokens = Tokens(0, 0, 0, 0)
        exit_code = 1
        injected: list[str] = []
        turn_ids: set[str] = set()
        error = ""
        cost_usd: float | None = None
        for received, line in lines:
            event = parse_line(line)
            if event is None:
                continue
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                model = str(event.get("model", ""))
            elif (
                kind == "system"
                and event.get("subtype") == "hook_response"
                and event.get("hook_event") == "SessionStart"
            ):
                injected.append(_hook_context(str(event.get("output", ""))))
            elif kind == "assistant":
                subagent = event.get("parent_tool_use_id") is not None
                message = event.get("message")
                message = message if isinstance(message, dict) else {}
                if not subagent:
                    turn_ids.add(str(message.get("id") or len(turn_ids)))
                    meter.add(
                        sum(
                            count(message.get("usage"), key)
                            for key in (
                                "input_tokens",
                                "cache_read_input_tokens",
                                "cache_creation_input_tokens",
                            )
                        )
                    )
                for block in _blocks(event):
                    if block.get("type") == "tool_use":
                        log.start(
                            str(block.get("id")),
                            str(block.get("name", "")),
                            block.get("input"),
                            received,
                            subagent,
                        )
            elif kind == "user":
                for block in _blocks(event):
                    if block.get("type") == "tool_result":
                        log.end(
                            str(block.get("tool_use_id")),
                            block.get("is_error"),
                            block.get("content"),
                        )
            elif kind == "result":
                usage = event.get("usage")
                usage = usage if isinstance(usage, dict) else {}
                final_text = str(event.get("result", ""))
                tokens = Tokens(
                    count(usage, "input_tokens"),
                    count(usage, "output_tokens"),
                    count(usage, "cache_read_input_tokens"),
                    count(usage, "cache_creation_input_tokens"),
                )
                total = event.get("total_cost_usd")
                cost_usd = (
                    float(total)
                    if isinstance(total, int | float) and not isinstance(total, bool)
                    else None
                )
                exit_code = 1 if event.get("is_error") else 0
                if event.get("is_error"):
                    error = ": ".join(
                        filter(None, (str(event.get("stop_reason", "")), final_text))
                    )
        return Trace(
            tool_calls=log.calls(),
            final_text=final_text,
            tokens=tokens,
            wall_s=wall_s,
            model=model,
            exit_code=exit_code,
            injected_context="\n\n".join(injected),
            error=error,
            context=meter.peak,
            start_context=meter.start,
            cost_usd=cost_usd,
            turns=len(turn_ids),
        )
