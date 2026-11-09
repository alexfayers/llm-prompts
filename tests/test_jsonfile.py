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
