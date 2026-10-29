"""Tests for the shared overlay-merge mechanism."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_prompts import install
from llm_prompts.overlay_merge import merge_agent_text


def test_seed_json_deep_merges_overlay_over_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pi_dir = tmp_path / "pi"
    monkeypatch.setattr(install, "_pi_agent_dir", lambda: pi_dir)
    for root, seed in (
        ("core", {"a": {"x": 1, "y": 2}, "b": 1}),
        ("overlay", {"a": {"y": 3}, "c": 4}),
    ):
        (tmp_path / root / "pi" / "seed").mkdir(parents=True)
        (tmp_path / root / "pi" / "seed" / "s.json").write_text(json.dumps(seed))

    offered = install._seed_pi_files([tmp_path / "core", tmp_path / "overlay"], {})

    assert json.loads((pi_dir / "s.json").read_text(encoding="utf-8")) == {
        "a": {"x": 1, "y": 3},
        "b": 1,
        "c": 4,
    }
    assert offered["s.json"] == ["a", "b", "c"]


def test_agent_merge_replaces_keys_and_keeps_base_body_when_overlay_has_none() -> None:
    base = "---\nname: w\ndescription: >\n  base\n  words\ntools: Read\n---\n\nBASE\n"
    overlay = "---\ndescription: new\ntools: [Bash]\nmodel: opus\n---\n"

    assert merge_agent_text(base, overlay) == (
        "---\nname: w\ndescription: new\ntools: Read, Bash\nmodel: opus\n---\n\nBASE\n"
    )
