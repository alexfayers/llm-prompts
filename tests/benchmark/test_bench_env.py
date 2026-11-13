import os
from pathlib import Path

import pytest

from llm_prompts.benchmark.cell.env import HOST_PI_VARS, MEMORY_VARS, isolated_env

HOME = Path("/sandbox/home")
VENV = Path("/sandbox/venv")


def test_config_dirs_point_inside_home(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HOME",
        "CLAUDE_CONFIG_DIR",
        "PI_CODING_AGENT_DIR",
        "CLINE_HOOKS_DATA_DIR",
        "GIT_CONFIG_GLOBAL",
    ):
        monkeypatch.setenv(name, f"/live/{name}")

    env = isolated_env(HOME, VENV)

    assert env["HOME"] == str(HOME)
    assert env["CLAUDE_CONFIG_DIR"] == str(HOME / ".claude")
    assert env["PI_CODING_AGENT_DIR"] == str(HOME / ".pi" / "agent")
    assert env["CLINE_HOOKS_DATA_DIR"] == str(HOME / ".cline-hooks")
    assert env["GIT_CONFIG_GLOBAL"] == str(HOME / ".gitconfig")


def test_telemetry_off_and_call_metrics_not_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DO_NOT_TRACK", "0")
    monkeypatch.setenv("MCP_MEMORY_CALL_METRICS_ENABLED", "true")

    env = isolated_env(HOME, VENV)

    assert env["DO_NOT_TRACK"] == "1"
    assert env["LLM_PROMPTS_NO_TELEMETRY"] == "1"
    assert env["LLM_PROMPTS_NO_UPDATE_CHECK"] == "1"
    assert env["MCP_MEMORY_BACKUP_ENABLED"] == "false"
    assert "MCP_MEMORY_CALL_METRICS_ENABLED" not in env


@pytest.mark.parametrize(
    ("host_path", "expected"),
    [
        ("/usr/bin:/bin", str(VENV / "bin") + os.pathsep + "/usr/bin:/bin"),
        (None, str(VENV / "bin")),
    ],
)
def test_venv_bin_is_prepended_to_path(
    monkeypatch: pytest.MonkeyPatch, host_path: str | None, expected: str
) -> None:
    if host_path is None:
        monkeypatch.delenv("PATH", raising=False)
    else:
        monkeypatch.setenv("PATH", host_path)

    assert isolated_env(HOME, VENV)["PATH"] == expected


def test_host_memory_pi_agent_and_git_vars_dropped_and_other_vars_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (*MEMORY_VARS, *HOST_PI_VARS):
        monkeypatch.setenv(name, "live")
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_PANE_ID", "p1")
    monkeypatch.setenv("GIT_DIR", "/live/.git")
    monkeypatch.setenv("PI_SUBAGENT_CHILD", "1")
    monkeypatch.setenv("PI_HERDSMAN_RUN_ID", "r1")
    monkeypatch.setenv("AWS_PROFILE", "dev")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")

    env = isolated_env(HOME, VENV)

    dropped = ("HERDR_", "GIT_DIR", "PI_SUBAGENT_", "PI_HERDSMAN_")
    assert not any(name.startswith(dropped) for name in env)
    assert not any(name in env for name in (*MEMORY_VARS, *HOST_PI_VARS))
    assert env["AWS_PROFILE"] == "dev"
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"


@pytest.mark.parametrize(
    "name",
    [
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "SSH_AUTH_SOCK",
    ],
)
def test_github_credentials_are_dropped(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "secret")

    assert name not in isolated_env(HOME, VENV)


def test_os_environ_is_not_mutated() -> None:
    before = dict(os.environ)

    isolated_env(HOME, VENV)

    assert dict(os.environ) == before
