"""Builds the isolated environment a benchmark cell runs in."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

MEMORY_VARS = ("MCP_MEMORY_PORT", "MCP_MEMORY_URL", "MCP_MEMORY_DB_PATH")
HOST_PI_VARS = (
    "PI_CACHE_RETENTION",
    "PI_CODING_AGENT_SESSION_DIR",
    "PI_SESSION_FILE",
    "PI_SESSION_ID",
    "PI_MODEL",
    "PI_PROVIDER",
    "PI_REASONING_LEVEL",
)
HOST_ONLY_PREFIXES = ("HERDR_", "GIT_", "PI_SUBAGENT_", "PI_HERDSMAN_")
HOST_ONLY_VARS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "SSH_AUTH_SOCK",
)
CHECK_VARS = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TZ", "GIT_CONFIG_GLOBAL")


def host_env() -> dict[str, str]:
    """Return the host environment without the variables of the host's agent and git, and without GitHub credentials."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(HOST_ONLY_PREFIXES) and k not in HOST_ONLY_VARS
    }


def isolated_env(home: Path, venv: Path) -> dict[str, str]:
    """Return the host environment redirected into the cell ``home`` and ``venv``."""
    env = host_env()
    env.update(
        HOME=str(home),
        CLAUDE_CONFIG_DIR=str(home / ".claude"),
        PI_CODING_AGENT_DIR=str(home / ".pi" / "agent"),
        CLINE_HOOKS_DATA_DIR=str(home / ".cline-hooks"),
        GIT_CONFIG_GLOBAL=str(home / ".gitconfig"),
        DO_NOT_TRACK="1",
        LLM_PROMPTS_NO_TELEMETRY="1",
        LLM_PROMPTS_NO_UPDATE_CHECK="1",
        MCP_MEMORY_BACKUP_ENABLED="false",
    )
    env.pop("MCP_MEMORY_CALL_METRICS_ENABLED", None)
    for name in (*MEMORY_VARS, *HOST_PI_VARS):
        env.pop(name, None)
    return with_venv(env, venv)


def check_env(cell_env: Mapping[str, str]) -> dict[str, str]:
    """Return only the variables of a cell's environment that a check command needs, so agent-written code sees no secrets."""
    return {name: cell_env[name] for name in CHECK_VARS if name in cell_env}


def with_venv(env: dict[str, str], venv: Path) -> dict[str, str]:
    """Return ``env`` with the ``venv`` bin directory first on ``PATH``."""
    bin_dir = str(venv / "bin")
    host_path = os.environ.get("PATH")
    return {
        **env,
        "PATH": f"{bin_dir}{os.pathsep}{host_path}" if host_path else bin_dir,
    }
