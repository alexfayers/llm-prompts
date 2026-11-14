"""The pi agent: its command line, output parsing and benchmark setup."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable, Mapping
from importlib import resources
from pathlib import Path

from llm_prompts.benchmark.agents.adapter import GUARD_ARGV, ModelNotSet
from llm_prompts.benchmark.agents.files import (
    copy_login,
    read_json,
    run_steps,
    write_json,
)
from llm_prompts.benchmark.cell.env import host_env
from llm_prompts.benchmark.paths import live_home
from llm_prompts.benchmark.runner.events import (
    CallLog,
    ContextMeter,
    count,
    parse_line,
)
from llm_prompts.benchmark.types import PreparedCell, Scenario, Session, Tokens, Trace

BUILTIN_TOOLS = {
    "bash": "Bash",
    "read": "Read",
    "edit": "Edit",
    "write": "Write",
    "grep": "Grep",
    "find": "Glob",
}
FAILED_STOP_REASONS = {"error", "aborted"}
HOOK_MESSAGE_TYPE = "cline-hooks"
DELEGATION_TOOLS = "*_agent*"
PERMISSION_CONFIG = Path(".pi/agent/extensions/pi-permission-system/config.json")
PATH_EDIT_TOOLS = ("edit", "write", "path_write")


def _text(message: Mapping[str, object]) -> str:
    content = message.get("content")
    blocks = content if isinstance(content, list) else []
    return "".join(
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )


BEDROCK_PROVIDER = "amazon-bedrock"


def _claude_region() -> str | None:
    env = read_json(live_home() / ".claude" / "settings.json", strict=False).get("env")
    region = env.get("AWS_REGION") if isinstance(env, dict) else None
    return region if isinstance(region, str) and region else None


def _pi_default_model() -> str:
    """Return the default model in the user's own pi settings."""
    path = live_home() / ".pi" / "agent" / "settings.json"
    model = read_json(path, strict=False).get("defaultModel")
    if isinstance(model, str) and model:
        return model
    raise ModelNotSet(f"pi has no default model: set defaultModel in {path}")


class PiAdapter:
    template_name = "pi"
    cumulative_cost = False
    delegation = False
    shared_dirs: tuple[Path, ...] = (Path(".pi/agent/npm"), Path(".npm"))
    git_packages: Path | None = Path(".pi/agent/git")

    @property
    def default_model(self) -> str:
        return _pi_default_model()

    @property
    def judge_model(self) -> str:
        return _pi_default_model()

    def point_memory(self, home: Path, url: str) -> None:
        config_path = home / ".pi" / "agent" / "mcp.json"
        config = read_json(config_path)
        config.setdefault("mcpServers", {})["memory"] = {"url": url}
        write_json(config_path, config)

    def install_guard(self, template_dir: Path) -> None:
        """Install the Bash guard, and let edits to rule and skill files run without a prompt that nobody answers."""
        config_path = template_dir / PERMISSION_CONFIG
        config = read_json(config_path)
        permission = config.setdefault("permission", {})
        for tool in PATH_EDIT_TOOLS:
            permission[tool] = {"*": "allow"}
        write_json(config_path, config)
        agent_dir = template_dir / ".pi" / "agent"
        (agent_dir / "extensions").mkdir(parents=True, exist_ok=True)
        extension = resources.files("llm_prompts.benchmark.guard") / "pi.ts"
        (agent_dir / "extensions" / "bench-guard.ts").write_text(extension.read_text())
        (agent_dir / "bench-guard.json").write_text(
            json.dumps({"argv": GUARD_ARGV}, indent=2) + "\n"
        )

    def copy_logins(self, home: Path) -> tuple[Path, ...]:
        return run_steps(
            (
                lambda: copy_login(
                    live_home() / ".pi" / "agent" / "auth.json",
                    home / ".pi" / "agent" / "auth.json",
                ),
            )
        )

    def judge_argv(self, system_prompt: str) -> list[str]:
        return [
            "pi", "-p", "--mode", "json", "--no-session", "-nt", "-ne", "-ns", "-nc", "--no-mcp",
            "--offline", "--thinking", "off", "--system-prompt", system_prompt,
        ]  # fmt: skip

    def judge_env(self, model: str, timeout_s: int) -> dict[str, str]:
        """Return the host env without the agent host and Git vars, plus the Claude region when pi resolves ``model`` to Bedrock."""
        env = host_env()
        if "AWS_REGION" in env:
            return env
        listing = subprocess.run(
            ["pi", "-ne", "--offline", "--list-models", model],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
        rows = listing.stdout.splitlines()[1:2]
        if (
            rows
            and rows[0].split()[0] == BEDROCK_PROVIDER
            and (region := _claude_region())
        ):
            env["AWS_REGION"] = region
        return env

    def sets_up_provider(self, prompts: Path) -> bool:
        """Return whether the overlay's pi settings choose a default model provider."""
        return "defaultProvider" in read_json(
            prompts / "pi" / "settings.json", strict=False
        )

    def command(
        self,
        prepared: PreparedCell,
        scenario: Scenario,
        model: str,
        session: Session | None = None,
    ) -> list[str]:
        """Return the pi argv for the scenario, saving the session when one is given."""
        if session is None:
            session_args = ["--no-session"]
        else:
            fork = ["--fork", session.fork] if session.fork else []
            session_args = [*fork, "--session-id", session.id]
        return [
            "pi",
            "--mode",
            "json",
            "--model",
            model,
            *session_args,
            "--offline",
            "--exclude-tools",
            DELEGATION_TOOLS,
            scenario.prompt,
        ]

    def replied(self, line: str) -> bool:
        event = parse_line(line)
        message = event.get("message") if event else None
        return (
            event is not None
            and event.get("type") == "message_end"
            and isinstance(message, dict)
            and message.get("role") == "assistant"
        )

    def parse(self, lines: Iterable[tuple[float, str]], wall_s: float) -> Trace:
        log = CallLog(BUILTIN_TOOLS)
        meter = ContextMeter()
        usage = [0, 0, 0, 0]
        final_text = model = ""
        stop_reason = ""
        error = ""
        cost_usd: float | None = None
        settled = False
        injected: list[str] = []
        turns = 0
        for at, line in lines:
            event = parse_line(line)
            if event is None:
                continue
            match event.get("type"):
                case "tool_execution_start":
                    log.start(
                        str(event.get("toolCallId")),
                        str(event.get("toolName", "")),
                        event.get("args"),
                        at,
                    )
                case "tool_execution_end":
                    result = event.get("result")
                    log.end(
                        str(event.get("toolCallId")),
                        event.get("isError"),
                        result.get("content") if isinstance(result, dict) else None,
                    )
                case "message_end" if (
                    isinstance(event.get("message"), dict)
                    and event["message"].get("role") == "custom"
                    and event["message"].get("customType") == HOOK_MESSAGE_TYPE
                ):
                    injected.append(str(event["message"].get("content", "")))
                case "message_end" if (
                    isinstance(event.get("message"), dict)
                    and event["message"].get("role") == "assistant"
                ):
                    message = event["message"]
                    turns += 1
                    call_usage = message.get("usage")
                    for i, key in enumerate(
                        ("input", "output", "cacheRead", "cacheWrite")
                    ):
                        usage[i] += count(call_usage, key)
                    meter.add(
                        sum(
                            count(call_usage, key)
                            for key in ("input", "cacheRead", "cacheWrite")
                        )
                    )
                    call_cost = (
                        call_usage.get("cost") if isinstance(call_usage, dict) else None
                    )
                    total = (
                        call_cost.get("total") if isinstance(call_cost, dict) else None
                    )
                    if isinstance(total, int | float) and not isinstance(total, bool):
                        cost_usd = (cost_usd or 0.0) + total
                    model = str(message.get("model", ""))
                    final_text = _text(message)
                    stop_reason = str(message.get("stopReason", ""))
                    error = (
                        str(message.get("errorMessage", ""))
                        if stop_reason in FAILED_STOP_REASONS
                        else ""
                    )
                case "agent_settled":
                    settled = True
        failed = not settled or stop_reason in FAILED_STOP_REASONS
        return Trace(
            tool_calls=log.calls(),
            final_text=final_text,
            tokens=Tokens(*usage),
            wall_s=wall_s,
            model=model,
            exit_code=int(failed),
            injected_context="\n\n".join(injected),
            error=error,
            context=meter.peak,
            start_context=meter.start,
            cost_usd=cost_usd,
            turns=turns,
        )
