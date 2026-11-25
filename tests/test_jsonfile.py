"""Tests for the atomic JSON writer."""

from __future__ import annotations

import json
from pathlib import Path

from llm_prompts.jsonfile import write_json_atomic


def test_writes_json_and_leaves_no_scratch_file(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "data.json"

    write_json_atomic(path, {"a": 1})

    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
    assert [p.name for p in path.parent.iterdir()] == ["data.json"]


def test_write_through_a_symlink_updates_its_target(tmp_path: Path) -> None:
    target = tmp_path / "dotfiles" / "data.json"
    target.parent.mkdir()
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "data.json"
    link.symlink_to(target)

    write_json_atomic(link, {"a": 1})

    assert link.is_symlink()
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert sorted(p.name for p in target.parent.iterdir()) == ["data.json"]
