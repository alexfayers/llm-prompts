"""Tests for the one-time copy of a tool's files into the shared root."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from llm_prompts.path_migration import RECORD, migrate


def _old_and_new(tmp_path: Path) -> tuple[Path, Path, Path]:
    old = tmp_path / "old"
    (old / "plugins").mkdir(parents=True)
    (old / "config.toml").write_text("a = 1\n", encoding="utf-8")
    (old / "plugins" / "x").write_text("x", encoding="utf-8")
    return old, tmp_path / "root" / "tool", tmp_path / "root" / "tool" / "config"


def test_copies_files_and_folders_then_records_them(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)

    migrate(
        tool_root,
        [
            (old / "config.toml", new / "config.toml"),
            (old / "plugins", new / "plugins"),
        ],
    )

    assert (new / "config.toml").read_text(encoding="utf-8") == "a = 1\n"
    assert (new / "plugins" / "x").read_text(encoding="utf-8") == "x"
    assert sorted(p.name for p in new.iterdir()) == ["config.toml", "plugins"]
    record = json.loads((tool_root / RECORD).read_text(encoding="utf-8"))
    assert record["copied"] == {
        str(old / "config.toml"): str(new / "config.toml"),
        str(old / "plugins"): str(new / "plugins"),
    }


def test_leaves_the_old_files_in_place(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)

    migrate(tool_root, [(old / "config.toml", new / "config.toml")])

    assert sorted(p.name for p in old.iterdir()) == ["config.toml", "plugins"]
    assert (old / "config.toml").read_text(encoding="utf-8") == "a = 1\n"


def test_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    (new / "plugins").mkdir(parents=True)
    (new / "config.toml").write_text("b = 2\n", encoding="utf-8")
    (new / "plugins" / "x").write_text("mine", encoding="utf-8")

    migrate(
        tool_root,
        [
            (old / "config.toml", new / "config.toml"),
            (old / "plugins", new / "plugins"),
        ],
    )

    assert (new / "config.toml").read_text(encoding="utf-8") == "b = 2\n"
    assert (new / "plugins" / "x").read_text(encoding="utf-8") == "mine"


def test_a_file_created_during_the_copy_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    real_copy = shutil.copy2

    def racing_copy(source: str | Path, target: str | Path) -> object:
        (new / "config.toml").write_text("racer\n", encoding="utf-8")
        return real_copy(source, target)

    monkeypatch.setattr(shutil, "copy2", racing_copy)
    migrate(tool_root, [(old / "config.toml", new / "config.toml")])

    assert (new / "config.toml").read_text(encoding="utf-8") == "racer\n"
    assert sorted(p.name for p in new.iterdir()) == ["config.toml"]


def test_copies_a_symlink_as_a_symlink(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    (old / "link").symlink_to("config.toml")

    migrate(tool_root, [(old / "link", new / "link")])

    assert os.readlink(new / "link") == "config.toml"


def test_runs_only_once(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    moves = [(old / "config.toml", new / "config.toml")]
    migrate(tool_root, moves)
    (new / "config.toml").unlink()

    migrate(tool_root, moves)

    assert not (new / "config.toml").exists()


def test_a_failed_copy_is_finished_on_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    (old / "plugins" / "y").write_text("y", encoding="utf-8")
    moves = [(old / "plugins", new / "plugins")]
    real_copy = shutil.copy2

    def failing_copy(source: str | Path, target: str | Path) -> object:
        if Path(source).name == "y":
            raise OSError("disk full")
        return real_copy(source, target)

    monkeypatch.setattr(shutil, "copy2", failing_copy)
    migrate(tool_root, moves)
    assert not (tool_root / RECORD).exists()
    assert sorted(p.name for p in (new / "plugins").iterdir()) == ["x"]

    monkeypatch.setattr(shutil, "copy2", real_copy)
    migrate(tool_root, moves)

    assert (new / "plugins" / "y").read_text(encoding="utf-8") == "y"
    assert (tool_root / RECORD).exists()


def test_the_lock_file_keeps_its_content(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    tool_root.mkdir(parents=True)
    (tool_root / ".migrate.lock").write_text("kept", encoding="utf-8")

    migrate(tool_root, [(old / "config.toml", new / "config.toml")])

    assert (tool_root / ".migrate.lock").read_text(encoding="utf-8") == "kept"


def test_a_symlinked_lock_file_stops_the_run(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    tool_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("kept", encoding="utf-8")
    (tool_root / ".migrate.lock").symlink_to(outside)

    with pytest.raises(OSError):
        migrate(tool_root, [(old / "config.toml", new / "config.toml")])

    assert outside.read_text(encoding="utf-8") == "kept"
    assert not (new / "config.toml").exists()


@pytest.mark.parametrize("link", ["config", "config/plugins"])
def test_never_copies_through_a_symlinked_destination_folder(
    tmp_path: Path, link: str
) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tool_root / link).parent.mkdir(parents=True, exist_ok=True)
    (tool_root / link).symlink_to(outside)

    migrate(
        tool_root,
        [
            (old / "config.toml", new / "config.toml"),
            (old / "plugins", new / "plugins"),
        ],
    )

    assert list(outside.iterdir()) == []
    assert not (tool_root / RECORD).exists()


def test_new_folders_are_private_and_files_keep_their_mode(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    (old / "plugins" / "shared").mkdir(mode=0o755)
    (old / "plugins" / "shared").chmod(0o755)
    (old / "plugins" / "x").chmod(0o640)

    migrate(tool_root, [(old / "plugins", new / "plugins")])

    assert (new / "plugins").stat().st_mode & 0o777 == 0o700
    assert (new / "plugins" / "shared").stat().st_mode & 0o777 == 0o700
    assert (new / "plugins" / "x").stat().st_mode & 0o777 == 0o640
    assert new.stat().st_mode & 0o777 == 0o700
    assert tool_root.stat().st_mode & 0o777 == 0o700
