"""Share the heavy, read-only parts of a variant template between the cells of a run."""

from __future__ import annotations

import os
import re
import shutil
import stat
import threading
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Self

from llm_prompts.benchmark import paths
from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.cell.audit import WRITE_BITS, entries
from llm_prompts.benchmark.paths import new_shared_root
from llm_prompts.benchmark.types import Agent


def rewrite_paths(root: Path, old: Path, new: Path) -> None:
    """Replace ``old`` with ``new`` in every regular file under ``root``."""
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if str(old).encode() in data:
            path.write_bytes(data.replace(str(old).encode(), str(new).encode()))


def ignoring(template: Path, agent: Agent) -> Callable[[str, list[str]], set[str]]:
    """Return a ``copytree`` ignore function that skips the shared folders of ``template``."""
    shared = {template / folder for folder in AGENTS[agent].shared_dirs}

    def ignore(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if Path(directory, name) in shared}

    return ignore


def _make_read_only(root: Path) -> None:
    for path in entries(root):
        path.chmod(path.stat().st_mode & ~WRITE_BITS)


def remove_tree(root: Path) -> None:
    for path in entries(root):
        if path.is_dir():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
    shutil.rmtree(root)


ROOT_OWNER = re.compile(
    rf"(?:{re.escape(paths.SHARED_ROOT_PREFIX)}|{re.escape(paths.CELL_ROOT_PREFIX)})(\d+)-"
)


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def remove_stale_roots() -> None:
    """Delete the cell and store roots that a benchmark process which no longer runs left behind."""
    for root in paths.work_dir().iterdir():
        owner = ROOT_OWNER.match(root.name)
        if owner and not _running(int(owner[1])):
            remove_tree(root)


class SharedStores:
    """Read-only copies of the shared template and live folders, built once per source."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stores: dict[Path, Path] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()

    def roots(self) -> tuple[Path, ...]:
        """Return the root of every store built so far."""
        with self._lock:
            return tuple(self._stores.values())

    def link(self, home: Path, template: Path, agent: Agent) -> None:
        """Link the shared folders of ``template`` into ``home``."""
        folders = [f for f in AGENTS[agent].shared_dirs if (template / f).is_dir()]
        if not folders:
            return
        store = self._store(template, folders)
        for folder in folders:
            (home / folder).parent.mkdir(parents=True, exist_ok=True)
            (home / folder).symlink_to(store / folder)

    def link_live(self, home: Path, live: Path, folder: Path) -> None:
        """Link the live ``folder`` into ``home`` unless it exists there or is absent."""
        if not (live / folder).is_dir() or os.path.lexists(home / folder):
            return
        store = self._store(live, [folder], rewrite=False)
        (home / folder).parent.mkdir(parents=True, exist_ok=True)
        (home / folder).symlink_to(store / folder)

    def _store(self, template: Path, folders: list[Path], rewrite: bool = True) -> Path:
        with self._lock:
            if template not in self._stores:
                root = new_shared_root()
                try:
                    for folder in folders:
                        shutil.copytree(template / folder, root / folder, symlinks=True)
                    if rewrite:
                        rewrite_paths(root, template, root)
                    _make_read_only(root)
                except BaseException:
                    remove_tree(root)
                    raise
                self._stores[template] = root
            return self._stores[template]

    def close(self) -> None:
        """Delete every store."""
        with self._lock:
            roots, self._stores = list(self._stores.values()), {}
        for root in roots:
            remove_tree(root)
