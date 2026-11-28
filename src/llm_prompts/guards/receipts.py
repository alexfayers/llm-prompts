"""Test-run receipts bound to a fingerprint of a repo's working tree."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Iterable
from pathlib import Path

from .. import home
from ..jsonfile import write_json_atomic

PROBE_TIMEOUT_SECONDS = 5


def _git(toplevel: Path, *args: str) -> str | None:
    """Return the output of a git command in `toplevel`, or None when it fails."""
    ran = subprocess.run(
        ["git", "-C", str(toplevel), *args], capture_output=True, check=False
    )
    return ran.stdout.decode() if ran.returncode == 0 else None


def _tool_version(tool: str, toplevel: Path) -> bytes | None:
    """Return the output of `<tool> --version` run in the repo, or None where it fails or takes over the probe timeout."""
    try:
        ran = subprocess.run(
            [tool, "--version"],
            capture_output=True,
            check=False,
            cwd=toplevel,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return ran.stdout + ran.stderr if ran.returncode == 0 else None


def tree_fingerprint(toplevel: Path, tools: Iterable[str] = ()) -> str:
    """Hash the path, kind, executable bit and content of every tracked and untracked file that is not ignored, and the version of each tool.

    A submodule counts by the commit its checkout is on. A failed git call or tool
    version probe gives a random hash, so no receipt ever matches it.
    """
    staged = _git(toplevel, "ls-files", "-z", "--stage")
    others = _git(toplevel, "ls-files", "-z", "--others", "--exclude-standard")
    if staged is None or others is None:
        return uuid.uuid4().hex
    names = {name for name in others.split("\0") if name}
    submodules = set()
    for line in filter(None, staged.split("\0")):
        meta, name = line.split("\t", 1)
        names.add(name)
        if meta.startswith("160000"):
            submodules.add(name)
    digest = hashlib.sha256()
    for tool in sorted(set(tools)):
        version = _tool_version(tool, toplevel)
        if version is None:
            return uuid.uuid4().hex
        digest.update(b"tool\0" + tool.encode() + b"\0" + version + b"\0")
    for name in sorted(names):
        path = toplevel / name
        if name in submodules:
            head = _git(path, "rev-parse", "HEAD")
            if head is None:
                return uuid.uuid4().hex
            content = b"commit\0" + head.encode()
        elif path.is_symlink():
            content = b"link\0" + os.readlink(path).encode()
        elif path.is_file():
            executable = b"x" if os.access(path, os.X_OK) else b"-"
            content = b"file" + executable + b"\0" + path.read_bytes()
        else:
            continue
        digest.update(name.encode() + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def _key(toplevel: Path, command: str) -> str:
    """Return the receipt key of a repo, or of one command run in it."""
    return f"{toplevel}\0{command}" if command else str(toplevel)


class ReceiptStore:
    """Remembers the tree fingerprint at each repo's last passing test run."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or home.data_dir("receipts.json")

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            receipts: dict[str, str] = json.loads(
                self._path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            return {}
        return receipts

    def record(self, toplevel: Path, fingerprint: str, command: str = "") -> None:
        """Store the fingerprint of a passing test run in the repo, or of its run of the command, holding a lock so parallel sessions keep each other's receipts."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.with_name(f"{self._path.name}.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            write_json_atomic(
                self._path, {**self._read(), _key(toplevel, command): fingerprint}
            )

    def stored(self, toplevel: Path, command: str = "") -> str | None:
        """Return the value stored for the repo, or for the command run in it, or None."""
        return self._read().get(_key(toplevel, command))

    def fresh(self, toplevel: Path, fingerprint: str, command: str = "") -> bool:
        """Report whether the last passing test run in the repo, or of the command, saw this fingerprint."""
        return self.stored(toplevel, command) == fingerprint
