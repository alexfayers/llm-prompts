import errno
import json
import os
import shutil
import stat
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import FakeSubprocess

from benchmark.conftest import FakeMemory
from llm_prompts.benchmark import paths
from llm_prompts.benchmark.cell.prepare import (
    IsolationBreach,
    prepare,
    prepare_fork,
    snapshot,
)
from llm_prompts.benchmark.cell.shared import SharedStores, remove_stale_roots
from llm_prompts.benchmark.types import Cell, Gate, MemoryEntity, Scenario, Variant

pytestmark = pytest.mark.usefixtures(
    "live", "cell_roots", "fake_memory", "fake_subprocess"
)
MakeCell = Callable[..., Cell]
DEAD_PID = 4_000_001
SEED = (MemoryEntity("alpha", "knowledge", ("a fact",)),)


@pytest.fixture
def live(tmp_path: Path, live_home: None, fake_memory: FakeMemory) -> Path:
    return tmp_path / "live"


@pytest.fixture
def cell_roots(tmp_path: Path, live_home: None, fake_memory: FakeMemory) -> Path:
    return tmp_path / "roots"


@pytest.fixture
def make_cell(tmp_path: Path, fake_variant: Variant) -> MakeCell:
    workspace = tmp_path / "fixture"
    workspace.mkdir()
    (workspace / "README.md").write_text("demo")
    scenario = Scenario(
        "demo", "light", ("claude", "pi"), workspace, "demo-project", "do it", 60,
        Gate(0.34, 0.25, 0.5, 0.5), SEED, (),
    )  # fmt: skip
    return lambda agent="claude": Cell(fake_variant, agent, scenario, 0)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _json(path: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads(path.read_text())
    return data


def test_claude_cell_gets_isolated_home_workspace_memory_and_logins(
    make_cell: MakeCell,
    fake_variant: Variant,
    live: Path,
    fake_memory: FakeMemory,
) -> None:
    template = fake_variant.templates["claude"]
    hook = _write(template / ".claude" / "hook.sh", f"python {template}/run.py\n")
    _write(live / ".claude/.credentials.json", '{"token": "abc"}')
    _write(live / ".claude.json", json.dumps({"oauthAccount": {"id": 1}}))
    settings = {
        "awsCredentialExport": "export-cmd",
        "apiKeyHelper": f"{live}/.claude/helper.sh",
        "env": {"AWS_REGION": "us-west-2", "EDITOR": "vim"},
    }
    _write(live / ".claude/settings.json", json.dumps(settings))
    _write(live / ".aws/config", "[default]")

    with prepare(make_cell()) as prepared:
        home = prepared.home
        credentials = home / ".claude/.credentials.json"
        assert stat.S_IMODE(credentials.stat().st_mode) == 0o600
        for copied in (".claude/.claude.json", ".claude/settings.json"):
            assert stat.S_IMODE((home / copied).stat().st_mode) == 0o600
        config = _json(home / ".claude/.claude.json")
        assert config["oauthAccount"] == {"id": 1}
        assert config["mcpServers"] == {
            "memory": {"type": "http", "url": prepared.memory.url}
        }
        assert _json(home / ".claude/settings.json") == {
            "awsCredentialExport": "export-cmd",
            "env": {"TEMPLATE": "1", "AWS_REGION": "us-west-2"},
            "permissions": {"allow": ["mcp__memory__*"]},
        }
        assert (home / ".claude/hook.sh").read_text() == f"python {home}/run.py\n"
        assert prepared.env["HOME"] == str(home)
        assert prepared.env["MCP_MEMORY_URL"] == prepared.memory.url
        assert prepared.env["AWS_CONFIG_FILE"] == str(live / ".aws/config")
        assert fake_memory.entities(prepared.memory) == prepared.seeded == SEED

    assert hook.read_text() == f"python {template}/run.py\n"


def test_seen_root_gives_the_agent_fixed_paths_and_host_steps_real_ones(
    make_cell: MakeCell,
    fake_variant: Variant,
    fake_memory: FakeMemory,
    fake_subprocess: FakeSubprocess,
    tmp_path: Path,
) -> None:
    template = fake_variant.templates["claude"]
    _write(template / ".claude" / "hook.sh", f"python {template}/run.py\n")
    seen = tmp_path / "fixed"

    with prepare(make_cell(), seen) as prepared:
        assert (
            prepared.home / ".claude/hook.sh"
        ).read_text() == f"python {seen / 'home'}/run.py\n"
        assert prepared.env["HOME"] == str(seen / "home")
        assert fake_memory.calls == [("demo-project", seen / "workspace")]
        assert prepared.home.parent != seen
        git_env = fake_subprocess.calls[0][1]["env"]
        assert git_env["GIT_CONFIG_GLOBAL"] == str(prepared.home / ".gitconfig")


def test_fork_copies_the_finished_cell_and_gets_its_own_memory_server(
    make_cell: MakeCell, cell_roots: Path, fake_memory: FakeMemory
) -> None:
    cell = make_cell("pi")
    with prepare(cell) as base:
        _write(base.workspace / "new.py", "edited")
        _write(base.home / ".pi/agent/sessions/s.jsonl", "{}")
        root = snapshot(base)

        with prepare_fork(cell, root, base) as fork:
            assert fork.root == root != base.root
            assert (fork.workspace / "new.py").read_text() == "edited"
            assert (fork.home / ".pi/agent/sessions/s.jsonl").exists()
            assert fork.memory != base.memory
            assert _json(fork.home / ".pi/agent/mcp.json")["mcpServers"] == {
                "memory": {"url": fork.memory.url}
            }
            assert fork.env["MCP_MEMORY_URL"] == fork.memory.url
            assert fork.env["HOME"] == base.env["HOME"]
            assert fork.seeded == base.seeded
            _write(fork.workspace / "only-fork.py", "x")
            assert not (base.workspace / "only-fork.py").exists()

        assert not root.exists()
        assert fake_memory.stopped.count(base.memory) == 0


def test_fork_audit_skips_the_session_transcript_but_not_the_workspace(
    make_cell: MakeCell, live: Path
) -> None:
    cell = make_cell("pi")
    with prepare(cell) as base:
        _write(base.home / ".pi/agent/sessions/s.jsonl", f"docs {live}/.pi/doc.md")
        with prepare_fork(cell, snapshot(base), base):
            pass

        _write(base.workspace / "notes.txt", f"see {live}/.pi/agent")
        with pytest.raises(IsolationBreach), prepare_fork(cell, snapshot(base), base):
            pass


def test_pi_cell_copies_auth_and_links_the_live_git_packages_and_npm_cache(
    make_cell: MakeCell, fake_variant: Variant, live: Path, cell_roots: Path
) -> None:
    _write(live / ".pi/agent/auth.json", '{"key": "k"}')
    _write(live / ".pi/agent/git/host/pkg/index.ts", "export {}")
    _write(fake_variant.templates["pi"] / ".npm/_cacache/index", "cached")

    with SharedStores() as stores:
        with prepare(make_cell("pi"), stores=stores) as prepared:
            agent_dir = prepared.home / ".pi/agent"
            assert (agent_dir / "auth.json").read_text() == '{"key": "k"}'
            assert (agent_dir / "git").is_symlink()
            assert (agent_dir / "git/host/pkg/index.ts").read_text() == "export {}"
            assert (prepared.home / ".npm").is_symlink()
            assert (prepared.home / ".npm/_cacache/index").read_text() == "cached"
            assert not any(p.name == "index.ts" for p in prepared.root.rglob("*"))
            with pytest.raises(PermissionError):
                (agent_dir / "git/host/pkg/index.ts").write_text("changed")
        assert (live / ".pi/agent/git/host/pkg/index.ts").read_text() == "export {}"


@pytest.mark.parametrize("outcome", ["normal", "error", "breach"])
def test_root_removed_and_memory_stopped_on_exit(
    make_cell: MakeCell,
    fake_variant: Variant,
    live: Path,
    cell_roots: Path,
    fake_memory: FakeMemory,
    outcome: str,
) -> None:
    _write(live / ".claude.json", {"normal": "{", "breach": "[]"}.get(outcome, ""))
    if outcome == "breach":
        leak = fake_variant.templates["claude"] / ".claude" / "leak.txt"
        _write(leak, f"path {live / '.claude'}\n")
    expected = {"error": KeyError, "breach": IsolationBreach}.get(outcome)

    with (
        pytest.raises(expected) if expected else nullcontext(),
        prepare(make_cell("pi" if outcome == "error" else "claude")),
    ):
        if outcome == "error":
            raise KeyError

    assert list(cell_roots.iterdir()) == []
    assert fake_memory.stopped == fake_memory.started


def _npm_file(variant: Variant) -> Path:
    return variant.templates["pi"] / ".pi/agent/npm/node_modules/pkg/index.js"


def test_pi_cell_links_the_read_only_npm_packages_instead_of_copying_them(
    make_cell: MakeCell, fake_variant: Variant
) -> None:
    template = fake_variant.templates["pi"]
    _write(_npm_file(fake_variant), "x" * 4096)
    _write(template / ".pi/agent/npm/package-lock.json", f"{template}/.pi/agent/npm")

    with prepare(make_cell("pi")) as prepared:
        link = prepared.home / ".pi/agent/npm"
        assert link.is_symlink()
        assert (link / "node_modules/pkg/index.js").read_text() == "x" * 4096
        copied = [p for p in prepared.root.rglob("*") if p.name == "index.js"]
        assert copied == []
        assert str(template) not in (link / "package-lock.json").read_text()
        assert (prepared.home / ".pi/agent/mcp.json").is_file()


def test_shared_npm_packages_cannot_be_written_through_the_cell_home(
    make_cell: MakeCell, fake_variant: Variant
) -> None:
    _write(_npm_file(fake_variant), "original")

    with prepare(make_cell("pi")) as prepared:
        shared = prepared.home / ".pi/agent/npm/node_modules/pkg"
        with pytest.raises(PermissionError):
            (shared / "index.js").write_text("changed")
        with pytest.raises(PermissionError):
            (shared / "new.js").write_text("added")
        with pytest.raises(PermissionError):
            (shared / "index.js").unlink()

    assert _npm_file(fake_variant).read_text() == "original"


def test_cells_of_a_run_share_one_store_that_forks_link_too(
    make_cell: MakeCell, fake_variant: Variant, cell_roots: Path
) -> None:
    _write(_npm_file(fake_variant), "x")
    cell = make_cell("pi")

    with SharedStores() as stores:
        with (
            prepare(cell, stores=stores) as first,
            prepare(cell, stores=stores) as second,
        ):
            root = snapshot(first)
            target = (first.home / ".pi/agent/npm").readlink()
            assert (second.home / ".pi/agent/npm").readlink() == target
            assert (root / "home/.pi/agent/npm").readlink() == target
            assert target.is_relative_to(stores.roots()[0])
            assert len(stores.roots()) == 1
        shutil.rmtree(root)

    assert list(cell_roots.iterdir()) == []


def test_cell_is_refused_when_an_earlier_cell_made_the_shared_store_writable(
    make_cell: MakeCell, fake_variant: Variant
) -> None:
    _write(_npm_file(fake_variant), "x")
    cell = make_cell("pi")

    with SharedStores() as stores:
        with prepare(cell, stores=stores) as first:
            (first.home / ".pi/agent/npm/node_modules/pkg/index.js").chmod(0o644)
            with (
                pytest.raises(IsolationBreach, match="writable"),
                prepare_fork(cell, snapshot(first), first, stores),
            ):
                pass
        with (
            pytest.raises(IsolationBreach, match="writable"),
            prepare(cell, stores=stores),
        ):
            pass


def test_setup_commands_run_in_the_workspace_after_the_first_commit(
    make_cell: MakeCell, fake_subprocess: FakeSubprocess
) -> None:
    cell = make_cell()
    scenario = replace(cell.scenario, setup=("git branch x", "git tag y"))

    with prepare(replace(cell, scenario=scenario)) as prepared:
        *_, first, second = fake_subprocess.calls
        assert [argv for argv, _ in (first, second)] == [
            ["sh", "-c", "git branch x"],
            ["sh", "-c", "git tag y"],
        ]
        assert first[1]["cwd"] == prepared.workspace
        assert first[1]["env"]["GIT_CONFIG_GLOBAL"] == str(prepared.home / ".gitconfig")


def test_roots_of_dead_runs_are_swept_and_those_of_live_runs_are_kept(
    cell_roots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead = [
        _write(cell_roots / f"{prefix}{DEAD_PID}-x" / "home" / "f", "x").parent.parent
        for prefix in (paths.CELL_ROOT_PREFIX, paths.SHARED_ROOT_PREFIX)
    ]
    live_root = _write(
        cell_roots / f"{paths.CELL_ROOT_PREFIX}{os.getpid()}-x" / "f", "x"
    ).parent
    other = _write(cell_roots / "unrelated" / "f", "x").parent
    (dead[1] / "home" / "f").chmod(0o444)
    (dead[1] / "home").chmod(0o555)

    def kill(pid: int, sig: int) -> None:
        if pid == DEAD_PID:
            raise ProcessLookupError

    monkeypatch.setattr(os, "kill", kill)

    remove_stale_roots()

    assert [path.exists() for path in (*dead, live_root, other)] == [
        False,
        False,
        True,
        True,
    ]


def test_a_snapshot_that_runs_out_of_disk_leaves_no_root_behind(
    make_cell: MakeCell, cell_roots: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    with prepare(make_cell("pi")) as base:
        before = set(cell_roots.iterdir())
        monkeypatch.setattr(shutil, "copytree", full)
        with pytest.raises(OSError, match="No space"):
            snapshot(base)

        assert set(cell_roots.iterdir()) == before


def test_a_declared_copy_gives_the_cell_its_own_writable_copy_of_a_host_home_file(
    make_cell: MakeCell,
    live: Path,
    declare_home: Callable[[dict[str, dict[str, list[str]]]], None],
) -> None:
    declare_home({".session": {"copy": ["token"]}})
    _write(live / ".session/token", "secret")
    _write(live / ".session/other", "left out")

    with prepare(make_cell()) as prepared:
        copy = prepared.home / ".session" / "token"
        assert copy.read_text() == "secret"
        assert not copy.is_symlink()
        assert not (prepared.home / ".session" / "other").exists()
        (prepared.home / ".session" / "token.lock").write_text("lock")
        copy.write_text("changed")

    assert (live / ".session/token").read_text() == "secret"
    assert not (live / ".session/token.lock").exists()


def test_without_the_os_sandbox_a_cell_gets_no_link_into_the_host_home(
    make_cell: MakeCell,
    live: Path,
    declare_home: Callable[[dict[str, dict[str, list[str]]]], None],
) -> None:
    declare_home({".tools": {"link": ["bin"]}})
    _write(live / ".tools/bin/run", "#!/bin/sh")

    with prepare(make_cell(), os_sandbox=True) as prepared:
        assert (prepared.home / ".tools/bin").is_symlink()

    with (
        pytest.raises(IsolationBreach, match="OS sandbox"),
        prepare(make_cell(), os_sandbox=False),
    ):
        pass
