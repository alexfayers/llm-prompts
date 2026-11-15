"""Check that every shipped pi extension exports a default factory and starts with a summary line."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

DEFAULT_FACTORY = re.compile(r"^export default (async )?function\b", re.MULTILINE)
SUMMARY_LINE = re.compile(r"// (?!(Commands|Config|Env):)\S")


def extension_entries(extensions_dir: Path) -> list[Path]:
    """List the files pi loads from an extensions directory.

    Args:
        extensions_dir: A `pi/extensions` directory; may not exist.

    Returns:
        Each top-level `*.ts` file and each subdirectory's `index.ts`, sorted by path.
    """
    return sorted([*extensions_dir.glob("*.ts"), *extensions_dir.glob("*/index.ts")])


def find_missing_default_factory(roots: Iterable[Path]) -> list[Path]:
    """List pi extension files under the roots that lack a default factory.

    Args:
        roots: Prompt roots whose pi extension entry files are checked.
    """
    return [
        extension
        for root in roots
        for extension in extension_entries(root / "pi" / "extensions")
        if not DEFAULT_FACTORY.search(extension.read_text(encoding="utf-8"))
    ]


def find_missing_summary_header(roots: Iterable[Path]) -> list[Path]:
    """List pi extension files under the roots whose first line is not a `// ` summary.

    Args:
        roots: Prompt roots whose pi extension entry files are checked.
    """
    return [
        extension
        for root in roots
        for extension in extension_entries(root / "pi" / "extensions")
        if not SUMMARY_LINE.match(extension.read_text(encoding="utf-8"))
    ]
