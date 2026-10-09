"""Tests for the pi extension default-factory check."""

from __future__ import annotations

from pathlib import Path

from llm_prompts.extension_factories import find_missing_default_factory


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
