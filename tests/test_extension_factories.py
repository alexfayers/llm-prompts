"""Tests for the pi extension default-factory check."""

from __future__ import annotations

from pathlib import Path

from llm_prompts.extension_factories import (
    find_missing_default_factory,
    find_missing_summary_header,
)


def _write_extension(root: Path, name: str, source: str) -> Path:
    path = root / "pi" / "extensions" / f"{name}.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_lists_only_extensions_without_a_default_factory(tmp_path: Path) -> None:
    _write_extension(tmp_path, "sync", "export default function (pi) {}\n")
    _write_extension(tmp_path, "async", "export default async function (pi) {}\n")
    missing = _write_extension(tmp_path, "named", "export function factory(pi) {}\n")

    assert find_missing_default_factory([tmp_path]) == [missing]


def test_root_without_extensions_dir_is_ignored(tmp_path: Path) -> None:
    assert find_missing_default_factory([tmp_path]) == []


def test_lists_only_extensions_not_starting_with_a_summary(tmp_path: Path) -> None:
    _write_extension(tmp_path, "good", "// Does a thing.\n// Env: X (y)\n")
    no_comment = _write_extension(tmp_path, "bare", "import x from 'x';\n")
    env_first = _write_extension(tmp_path, "env", "// Env: X (y)\n")
    empty = _write_extension(tmp_path, "empty", "// \n// Does a thing.\n")

    assert find_missing_summary_header([tmp_path]) == [no_comment, empty, env_first]
