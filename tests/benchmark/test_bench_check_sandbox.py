"""Checks run agent-written code, so they run in the cell's OS sandbox with a minimal environment."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from benchmark.traces import make_trace
from llm_prompts.benchmark import paths
from llm_prompts.benchmark.cell.env import check_env
from llm_prompts.benchmark.runner.sandbox import SandboxPolicy
from llm_prompts.benchmark.scenarios.checks import evaluate
from llm_prompts.benchmark.scenarios.checks.context import CheckContext
from llm_prompts.benchmark.types import CheckSpec

pytestmark = [
    pytest.mark.real_io,
    pytest.mark.skipif(
        not (shutil.which("bwrap") or shutil.which("sandbox-exec")),
        reason="no OS sandbox",
    ),
]


def command_exit(command: str, workspace: Path, **context: object) -> bool:
    ctx = CheckContext(make_trace(), workspace, (), (), **context)  # type: ignore[arg-type]
    (outcome,) = evaluate([CheckSpec("command_exit", {"command": command})], ctx)
    return outcome.passed


def test_command_exit_cannot_write_outside_the_cell(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    probe = Path(__file__).parent / f"check-probe-{uuid.uuid4().hex}.txt"
    sandbox = SandboxPolicy((tmp_path,))
    try:
        assert not command_exit(f"touch {probe}", workspace, sandbox=sandbox)
        assert not probe.exists()
        assert command_exit("touch inside.txt", workspace, sandbox=sandbox)
        assert (workspace / "inside.txt").exists()
    finally:
        probe.unlink(missing_ok=True)


def test_command_exit_does_not_see_host_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BENCH_HOST_SECRET", "x")
    env = check_env({"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})

    assert command_exit('test -z "$BENCH_HOST_SECRET"', tmp_path, env=env)
    assert command_exit(f'test "$HOME" = "{tmp_path}"', tmp_path, env=env)


@pytest.mark.skipif(not shutil.which("bwrap"), reason="bwrap is absent")
def test_a_linux_cell_cannot_see_or_change_a_sibling_cell_in_the_temp_dir(
    tmp_path: Path,
) -> None:
    cell, sibling = tmp_path / "cell", tmp_path / "sibling"
    cell.mkdir()
    sibling.mkdir()
    (sibling / "memory.db").write_text("secret")
    sandbox = SandboxPolicy((cell,))

    assert command_exit(f"test ! -e {sibling}/memory.db", cell, sandbox=sandbox)
    assert not command_exit(f"touch {sibling}/new", cell, sandbox=sandbox)
    assert not (sibling / "new").exists()
    assert command_exit(f"touch {cell}/mine", cell, sandbox=sandbox)
    assert (cell / "mine").exists()


@pytest.mark.skipif(not shutil.which("bwrap"), reason="bwrap is absent")
def test_a_linux_cell_cannot_see_a_sibling_cell_in_the_work_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = Path(__file__).parent / f"work-{uuid.uuid4().hex}"
    cell, sibling = work / "cell", work / "sibling"
    cell.mkdir(parents=True)
    sibling.mkdir()
    (sibling / "memory.db").write_text("secret")
    monkeypatch.setattr(paths, "work_dir", lambda: work)
    sandbox = SandboxPolicy((cell,))
    try:
        assert command_exit(f"test ! -e {sibling}/memory.db", cell, sandbox=sandbox)
        assert command_exit(f"touch {cell}/mine", cell, sandbox=sandbox)
        assert (cell / "mine").exists()
    finally:
        shutil.rmtree(work)
