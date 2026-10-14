"""Check that every shipped pi extension exports a default factory and starts with a summary line."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

DEFAULT_FACTORY = re.compile(r"^export default (async )?function\b", re.MULTILINE)
SUMMARY_LINE = re.compile(r"// (?!(Commands|Config|Env):)\S")


def find_missing_default_factory(roots: Iterable[Path]) -> list[Path]:
    """List pi extension files under the roots that lack a default factory.

    Args:
        roots: Prompt roots whose `pi/extensions/*.ts` files are checked.
    """
    return [
        extension
        for root in roots
        for extension in sorted((root / "pi" / "extensions").glob("*.ts"))
        if not DEFAULT_FACTORY.search(extension.read_text(encoding="utf-8"))
    ]


def find_missing_summary_header(roots: Iterable[Path]) -> list[Path]:
    """List pi extension files under the roots whose first line is not a `// ` summary.

    Args:
        roots: Prompt roots whose `pi/extensions/*.ts` files are checked.
    """
    return [
        extension
        for root in roots
        for extension in sorted((root / "pi" / "extensions").glob("*.ts"))
        if not SUMMARY_LINE.match(extension.read_text(encoding="utf-8"))
    ]
