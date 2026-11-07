"""Run a stub agent under the real OS sandbox and the real mcp-memory."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

from benchmark.traces import make_trace
from llm_prompts.benchmark.cell.prepare import prepare
from llm_prompts.benchmark.cell.shared import SharedStores
from llm_prompts.benchmark.runner import process
from llm_prompts.benchmark.runner.process import execute
from llm_prompts.benchmark.runner.sandbox import SandboxPolicy
from llm_prompts.benchmark.types import (
    Cell,
    Gate,
    PreparedCell,
    Scenario,
    Session,
    Trace,
    Variant,
)

pytestmark = [
    pytest.mark.usefixtures("live_home"),
    pytest.mark.real_io,
    pytest.mark.skipif(
        not (shutil.which("mcp-memory") and shutil.which("bwrap")),
        reason="mcp-memory or bwrap is absent",
    ),
]


class _StubRunner:
    def __init__(self, mode: str, target: str) -> None:
        self.argv = (
            ["sh", "-c", 'echo x > "$0" 2>/dev/null && echo ok || echo fail', target]
            if mode == "write"
            else [
                "sh",
                "-c",
                'chmod u+w "$0"; echo x > "$0" && echo ok || echo fail',
                target,
            ]
            if mode == "unlock"
            else [
                "curl",
                "-s",
                "-m",
                "5",
                "--noproxy",
                "*",
                "-o",
                "/dev/null",
                "-w",
                "status:%{http_code}",
                target,
            ]
        )

    def command(
        self,
        prepared: PreparedCell,
        scenario: Scenario,
        model: str,
        session: Session | None = None,
    ) -> list[str]:
        return self.argv

    def parse(self, lines: Iterable[tuple[float, str]], wall_s: float) -> Trace:
        text = "".join(line for _, line in lines).strip()
        return make_trace(final_text=text, wall_s=wall_s, model="stub")


@pytest.fixture
def prepared(fake_variant: Variant, tmp_path: Path) -> Iterator[PreparedCell]:
    (tmp_path / "fixture").mkdir()
    (tmp_path / "fixture" / "README.md").write_text("demo")
    scenario = Scenario(
        "demo", "light", ("claude",), tmp_path / "fixture", "demo", "do it", 60,
        Gate(0.34, 0.25, 0.5, 0.5), (), (),
    )  # fmt: skip
    with prepare(Cell(fake_variant, "claude", scenario, 0)) as cell:
        yield cell


def test_sandbox_confines_writes_and_reaches_real_memory_server(
    prepared: PreparedCell, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = SandboxPolicy(writable=(prepared.root,))
    probe = Path(__file__).parent / f"sandbox-probe-{uuid.uuid4().hex}.txt"

    def run(mode: str, target: str, policy: SandboxPolicy | None) -> str:
        monkeypatch.setattr(process, "AGENTS", {"claude": _StubRunner(mode, target)})
        return execute(prepared, prepared.cell.scenario, "stub", policy).final_text

    try:
        assert run("write", str(probe), policy) == "fail"
        assert not probe.exists()
        assert run("write", str(prepared.workspace / "out.txt"), policy) == "ok"
        assert run("write", str(probe), None) == "ok"
        assert run("http", prepared.memory.url, policy) != "status:000"
    finally:
        probe.unlink(missing_ok=True)


def test_sandbox_keeps_the_shared_store_read_only_even_after_a_chmod(
    prepared: PreparedCell, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = tmp_path / "template"
    (template / ".pi/agent/npm").mkdir(parents=True)
    (template / ".pi/agent/npm/index.js").write_text("original")
    monkeypatch.setattr(process, "AGENTS", {"claude": _StubRunner("unlock", "")})

    with SharedStores() as stores:
        stores.link(prepared.home, template, "pi")
        [store] = stores.roots()
        shared = store / ".pi/agent/npm/index.js"
        runner = _StubRunner("unlock", str(shared))
        monkeypatch.setattr(process, "AGENTS", {"claude": runner})
        sandbox = SandboxPolicy((prepared.root,), read_only=(store,))

        assert (
            execute(prepared, prepared.cell.scenario, "stub", sandbox).final_text
            == "fail"
        )
        assert shared.read_text() == "original"
        assert (
            execute(
                prepared,
                prepared.cell.scenario,
                "stub",
                SandboxPolicy((prepared.root, store)),
            ).final_text
            == "ok"
        )
