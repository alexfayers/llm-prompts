"""Build the isolated home, workspace and memory server of a benchmark cell."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.agents.claude import CLAUDE_SETTINGS_KEYS
from llm_prompts.benchmark.agents.files import read_json
from llm_prompts.benchmark.cell import memory
from llm_prompts.benchmark.cell.audit import SESSION_DIRS, AuditHit, audit
from llm_prompts.benchmark.cell.env import isolated_env
from llm_prompts.benchmark.cell.home_dirs import (
    declared_home_dirs,
    link_home_dirs,
)
from llm_prompts.benchmark.cell.shared import SharedStores, ignoring, rewrite_paths
from llm_prompts.benchmark.paths import live_home, new_cell_root
from llm_prompts.benchmark.types import Cell, PreparedCell

COMMIT_MESSAGE = "chore: add demo project"
PLACEHOLDER_GITCONFIG = (
    "[user]\n\tname = benchmark\n\temail = benchmark@example.invalid\n"
)
ISOLATED_HOME_DIRS = (".local", ".config", ".cache")


def login_env() -> dict[str, str]:
    """Return the AWS credential variables that point at the live files."""
    aws = live_home() / ".aws"
    return {
        key: str(path)
        for key, name in (
            ("AWS_CONFIG_FILE", "config"),
            ("AWS_SHARED_CREDENTIALS_FILE", "credentials"),
        )
        if (path := aws / name).exists()
    }


def _helper_commands(home: Path) -> tuple[str, ...]:
    settings = read_json(home / ".claude" / "settings.json", strict=False)
    return tuple(
        words[0]
        for key in CLAUDE_SETTINGS_KEYS
        if isinstance(value := settings.get(key), str) and (words := shlex.split(value))
    )


def link_tool_dirs(home: Path, commands: Iterable[str], path: str) -> tuple[Path, ...]:
    """Link the live home directories holding ``commands`` into ``home`` and return the links."""
    links: list[Path] = []
    for command in commands:
        if not (found := shutil.which(command, path=path)):
            continue
        try:
            top = Path(found).relative_to(live_home()).parts[0]
        except ValueError:
            continue
        if top in ISOLATED_HOME_DIRS or os.path.lexists(home / top):
            continue
        (home / top).symlink_to(live_home() / top)
        links.append(home / top)
    return tuple(links)


class IsolationBreach(Exception):
    def __init__(self, hits: list[AuditHit]) -> None:
        super().__init__(", ".join(f"{hit.path}: {hit.marker}" for hit in hits))
        self.hits = hits


def _init_repo(workspace: Path, env: dict[str, str], setup: Iterable[str]) -> None:
    commands = [
        ["git", "init"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", COMMIT_MESSAGE],
        *(["sh", "-c", command] for command in setup),
    ]
    for argv in commands:
        subprocess.run(argv, cwd=workspace, env=env, check=True, capture_output=True)


def _discard(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)


@contextmanager
def prepare(
    cell: Cell, seen_root: Path | None = None, stores: SharedStores | None = None
) -> Iterator[PreparedCell]:
    """Build an isolated cell home, workspace and memory server, and yield them as a prepared cell.

    The agent sees the cell under ``seen_root`` when given, otherwise under its real root.
    The cell links the shared template folders from ``stores``, or from stores of its own.
    """
    root = new_cell_root()
    with ExitStack() as cleanup:
        cleanup.callback(_discard, root)
        stores = stores or cleanup.enter_context(SharedStores())
        home, workspace = root / "home", root / "workspace"
        seen = seen_root or root
        template = cell.variant.templates[cell.agent]
        shutil.copytree(
            template, home, symlinks=True, ignore=ignoring(template, cell.agent)
        )
        stores.link(home, template, cell.agent)
        rewrite_paths(home, template, seen / "home")
        shutil.copytree(cell.scenario.workspace, workspace, symlinks=True)
        host_env = isolated_env(home, cell.variant.venv)
        base_env = isolated_env(seen / "home", cell.variant.venv)
        with memory.start(
            home,
            cell.scenario.memory,
            cell.scenario.project,
            seen / "workspace",
            host_env,
        ) as handle:
            agent = AGENTS[cell.agent]
            agent.point_memory(home, handle.url)
            agent.copy_logins(home)
            if agent.git_packages:
                stores.link_live(home, live_home(), agent.git_packages)
            shared = {**handle.env(), **login_env()}
            env = {**base_env, **shared, **cell.variant.env}
            link_home_dirs(home, declared_home_dirs())
            link_tool_dirs(home, (cell.agent, *_helper_commands(home)), env["PATH"])
            gitconfig = home / ".gitconfig"
            if not gitconfig.exists():
                gitconfig.write_text(PLACEHOLDER_GITCONFIG)
            _init_repo(workspace, {**host_env, **shared}, cell.scenario.setup)
            if hits := audit(root, stores=stores.roots()):
                raise IsolationBreach(hits)
            yield PreparedCell(
                cell, root, home, workspace, env, handle, memory.read_entities(handle)
            )


def snapshot(base: PreparedCell) -> Path:
    """Copy the home, workspace and memory database of a prepared cell into a new cell root."""
    root = new_cell_root()
    try:
        shutil.copytree(
            base.home,
            root / "home",
            symlinks=True,
            ignore=shutil.ignore_patterns("memory.db*", "memory.log"),
        )
        shutil.copytree(base.workspace, root / "workspace", symlinks=True)
        memory.copy_database(base.memory, root / "home" / "memory.db")
    except BaseException:
        shutil.rmtree(root)
        raise
    return root


@contextmanager
def prepare_fork(
    cell: Cell, root: Path, base: PreparedCell, stores: SharedStores | None = None
) -> Iterator[PreparedCell]:
    """Start a memory server on the snapshot ``root`` of ``base`` and yield it as a prepared cell.

    A fresh follow-up has no saved sessions and counts the memory it starts with as its seed.

    The audit also checks the shared ``stores`` that ``base`` links.
    """
    try:
        home, workspace = root / "home", root / "workspace"
        if cell.scenario.fresh:
            for folder in SESSION_DIRS:
                if (home / folder).exists():
                    shutil.rmtree(home / folder)
        host_env = isolated_env(home, cell.variant.venv)
        with memory.start(
            home, None, cell.scenario.project, workspace, host_env
        ) as handle:
            AGENTS[cell.agent].point_memory(home, handle.url)
            if hits := audit(
                root,
                [home / folder for folder in SESSION_DIRS],
                stores.roots() if stores else (),
            ):
                raise IsolationBreach(hits)
            yield PreparedCell(
                cell,
                root,
                home,
                workspace,
                {**base.env, **handle.env()},
                handle,
                memory.read_entities(handle) if cell.scenario.fresh else base.seeded,
            )
    finally:
        _discard(root)
