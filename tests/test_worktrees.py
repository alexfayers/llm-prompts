"""Tests for the record of worktrees that contribute manages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm_prompts import home, worktrees
from llm_prompts.worktrees import (
    CorruptRecord,
    Link,
    WorktreeEntry,
    load_entries,
    save_entries,
)


def _entry(branch: str = "feat/a", **fields: Any) -> WorktreeEntry:
    return WorktreeEntry(
        **{
            "repo": "/r",
            "branch": branch,
            "path": "/w/a",
            "pr": None,
            "pr_state": None,
            "remote_head": None,
            "ready": False,
            **fields,
        }
    )


def test_record_path_defaults_next_to_the_other_config_files() -> None:
    assert worktrees.record_path() == home.config_dir() / "contribute-worktrees.json"


def test_record_path_can_be_pointed_elsewhere(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(worktrees.RECORD_ENV, str(tmp_path / "copy.json"))

    assert worktrees.record_path() == tmp_path / "copy.json"


def test_missing_record_is_empty(tmp_path: Path) -> None:
    assert load_entries(tmp_path / "record.json") == []


def test_entries_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    entries = [
        _entry(pr=7, pr_state="OPEN", remote_head="abc", ready=True),
        _entry("b"),
    ]

    save_entries(path, entries)

    assert load_entries(path) == entries


def test_corrupt_record_is_set_aside_and_names_rescan(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CorruptRecord, match="--rescan"):
        load_entries(path)

    assert not path.exists()
    [aside] = tmp_path.glob("record.json.corrupt-*")
    assert aside.read_text(encoding="utf-8") == "{not json"


def test_links_and_base_round_trip_and_old_records_load(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    linked = _entry(
        depends_on=(Link("/r", "feat/a", "o/r#7"),),
        base="abc",
        dropped_refs=("o/r#3",),
        copied="1700000000\tfeat: a",
    )

    save_entries(path, [linked])
    assert load_entries(path) == [linked]
    assert json.loads(path.read_text(encoding="utf-8"))["entries"][0]["depends_on"] == [
        {"repo": "/r", "branch": "feat/a", "ref": "o/r#7"}
    ]

    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "repo": "/r",
                        "branch": "b",
                        "path": "/w",
                        "pr": None,
                        "pr_state": None,
                        "remote_head": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    [old] = load_entries(path)
    assert (old.depends_on, old.base, old.dropped_refs, old.copied) == (
        (),
        None,
        (),
        None,
    )
