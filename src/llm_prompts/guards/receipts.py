"""Test-run receipts bound to a fingerprint of a repo's working tree."""

from __future__ import annotations

import fcntl
import hashlib
import json
import subprocess
from pathlib import Path

from .. import home
from ..jsonfile import write_json_atomic


def tree_fingerprint(toplevel: Path) -> str:
    """Hash the path and content of every tracked and untracked file that is not ignored."""
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(toplevel),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        check=False,
    ).stdout.decode()
    digest = hashlib.sha256()
    for name in sorted(set(listing.split("\0")) - {""}):
        path = toplevel / name
        if path.is_file():
            digest.update(
                name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest()
            )
    return digest.hexdigest()


class ReceiptStore:
    """Remembers the tree fingerprint at each repo's last passing test run."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or home.config_dir() / "receipts.json"

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

    def record(self, toplevel: Path, fingerprint: str) -> None:
        """Store the fingerprint of a passing test run in the repo, holding a lock so parallel sessions keep each other's receipts."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.with_name(f"{self._path.name}.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            write_json_atomic(self._path, {**self._read(), str(toplevel): fingerprint})

    def fresh(self, toplevel: Path, fingerprint: str) -> bool:
        """Report whether the repo's last passing test run saw this fingerprint."""
        return self._read().get(str(toplevel)) == fingerprint
