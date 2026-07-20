"""Scan a workspace for TODO.md files and TODO/FIXME/HACK/XXX/BUG markers."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

MARKERS = ("TODO", "FIXME", "HACK", "XXX", "BUG")
MARKER_RE = re.compile(r"\b(" + "|".join(MARKERS) + r")\b[:\s(-]*(.*)")
VENDOR_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "vendor",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        "target",
        ".next",
        "coverage",
    }
)


def list_files(root: Path) -> list[Path]:
    """Walk root, pruning hidden and VENDOR_DIRS directories, returning file paths."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in VENDOR_DIRS
        ]
        files.extend(Path(dirpath) / name for name in filenames)
    return files


def find_todos(root: Path) -> dict:
    """Scan the tree; return {root, files_scanned, todos, todo_files}."""
    files = list_files(root)
    todos: list[dict] = []
    for path in files:
        todos.extend(scan_file(path, root))
    todo_files = [str(f.relative_to(root)) for f in files if f.name == "TODO.md"]
    return {
        "root": str(root),
        "files_scanned": len(files),
        "todos": todos,
        "todo_files": todo_files,
    }


def scan_file(path: Path, root: Path) -> list[dict]:
    """Return marker hits ({file, line, type, task}) for one file; [] if unreadable/binary."""
    rel = str(path.relative_to(root))
    hits: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = MARKER_RE.search(line)
        if match:
            hits.append(
                {
                    "file": rel,
                    "line": lineno,
                    "type": match.group(1),
                    "task": match.group(2).strip(),
                }
            )
    return hits


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser: one optional `root` positional (default ".")."""
    parser = argparse.ArgumentParser(description="Scan a workspace for TODOs")
    parser.add_argument("root", nargs="?", default=".", help="Directory to scan")
    return parser


def main() -> None:
    """Parse args, run find_todos, json.dump the result to stdout."""
    args = build_parser().parse_args()
    result = find_todos(Path(args.root))
    json.dump(result, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
