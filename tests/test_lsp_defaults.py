"""Tests for the lsp-defaults pi extension."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
    / "lsp-defaults.ts"
)
_HARNESS = Path(__file__).parent / "context_total_harness.mjs"
_NODE = shutil.which("node")


def _can_strip_types() -> bool:
    if _NODE is None:
        return False
    probe = subprocess.run(
        [_NODE, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _can_strip_types(), reason="node with type stripping missing"
)


def _binary_dir(tmp_path: Path, name: str, *binaries: str) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    for binary in binaries:
        (directory / binary).write_text("#!/bin/sh\n")
        (directory / binary).chmod(0o755)
    return directory


def _sent_after_prompts(
    tmp_path: Path,
    path_dirs: list[Path],
    *,
    commands: list[str] | None = None,
    project_config: dict[str, Any] | None = None,
    events: tuple[str, ...] = ("session_start", "before_agent_start"),
) -> list[Any]:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    if project_config is not None:
        (project / ".pi-lsp.json").write_text(json.dumps(project_config))
    pi = {"$pi": "pi", "commands": ["lsp-config"] if commands is None else commands}
    steps: list[dict[str, Any]] = [{"fn": "default", "args": [pi]}]
    steps += [
        {"emit": event, "pi": "pi", "ctx": {"cwd": str(project)}} for event in events
    ]
    steps.append({"sent": "pi", "as": "sent"})
    config = tmp_path / "config.json"
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(exist_ok=True)
    config.write_text(
        json.dumps({"script": str(_SCRIPT), "agentDir": str(agent_dir), "steps": steps})
    )
    done = subprocess.run(
        [str(_NODE), str(_HARNESS), str(config)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.pathsep.join(map(str, path_dirs))},
    )
    output: dict[str, Any] = json.loads(done.stdout)
    assert "error" not in output, output["error"]
    sent: list[Any] = output["results"]["sent"]
    return sent


class TestPythonFallback:
    """Tests for switching Python to ty or ruff when pyright is missing."""

    @pytest.mark.parametrize("server", ["ty", "ruff"])
    def test_fallback_replaces_missing_pyright_once_per_session(
        self, tmp_path: Path, server: str
    ) -> None:
        only = _binary_dir(tmp_path, "bin", server)
        sent = _sent_after_prompts(
            tmp_path,
            [only],
            events=("session_start", "before_agent_start", "before_agent_start"),
        )
        assert sent == [
            [f"/lsp-config python {server} server", {"expandPromptTemplates": True}]
        ]

    def test_nothing_is_sent_when_pyright_is_installed(self, tmp_path: Path) -> None:
        both = _binary_dir(tmp_path, "bin", "ty", "pyright-langserver")
        assert _sent_after_prompts(tmp_path, [both]) == []

    def test_nothing_is_sent_when_ty_is_missing(self, tmp_path: Path) -> None:
        empty = _binary_dir(tmp_path, "bin")
        assert _sent_after_prompts(tmp_path, [empty]) == []

    def test_nothing_is_sent_when_the_project_configures_python(
        self, tmp_path: Path
    ) -> None:
        ty_only = _binary_dir(tmp_path, "bin", "ty")
        project_config = {"servers": {"python": {"command": "pylsp"}}}
        assert (
            _sent_after_prompts(tmp_path, [ty_only], project_config=project_config)
            == []
        )

    def test_nothing_is_sent_without_the_lsp_config_command(
        self, tmp_path: Path
    ) -> None:
        ty_only = _binary_dir(tmp_path, "bin", "ty")
        assert _sent_after_prompts(tmp_path, [ty_only], commands=["lsp"]) == []

    def test_a_new_session_applies_the_switch_again(self, tmp_path: Path) -> None:
        ty_only = _binary_dir(tmp_path, "bin", "ty")
        sent = _sent_after_prompts(
            tmp_path,
            [ty_only],
            events=(
                "session_start",
                "before_agent_start",
                "session_start",
                "before_agent_start",
            ),
        )
        assert len(sent) == 2
