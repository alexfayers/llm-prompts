"""Tests for the one-time copy of a tool's files into the shared root."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from llm_prompts.path_migration import migrate, unready_kinds


def _old_and_new(tmp_path: Path) -> tuple[Path, Path, Path]:
    old = tmp_path / "old"
    (old / "plugins").mkdir(parents=True)
    (old / "config.toml").write_text("a = 1\n", encoding="utf-8")
    (old / "plugins" / "x").write_text("x", encoding="utf-8")
    return old, tmp_path / "root" / "tool", tmp_path / "root" / "tool" / "config"


def test_copies_files_and_folders(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)

    failures = migrate(
        tool_root,
        [
            (old / "config.toml", new / "config.toml"),
            (old / "plugins", new / "plugins"),
        ],
    )

    assert failures == {}
    assert (new / "config.toml").read_text(encoding="utf-8") == "a = 1\n"
    assert (new / "plugins" / "x").read_text(encoding="utf-8") == "x"
    assert sorted(p.name for p in new.iterdir()) == ["config.toml", "plugins"]


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


def test_a_folder_created_during_the_copy_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    real_copy = shutil.copy2

    def racing_copy(source: str | Path, target: str | Path) -> object:
        new.mkdir(exist_ok=True)
        (new / "config.toml").write_text("racer\n", encoding="utf-8")
        return real_copy(source, target)

    monkeypatch.setattr(shutil, "copy2", racing_copy)
    failures = migrate(tool_root, [(old / "config.toml", new / "config.toml")])

    assert list(failures) == ["config"]
    assert (new / "config.toml").read_text(encoding="utf-8") == "racer\n"
    assert sorted(p.name for p in tool_root.iterdir()) == [
        ".migrate.lock",
        "config",
    ]


def test_copies_a_symlink_as_the_file_it_points_to(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    (old / "link").symlink_to("config.toml")

    migrate(tool_root, [(old / "link", new / "link")])

    assert not (new / "link").is_symlink()
    assert (new / "link").read_text(encoding="utf-8") == (
        old / "config.toml"
    ).read_text(encoding="utf-8")


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


def test_a_failed_folder_is_reported_left_unpublished_and_redone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    moves = [
        (old / "config.toml", new / "config.toml"),
        (old / "plugins", new / "plugins"),
    ]
    real_copy = shutil.copy2

    def failing_copy(source: str | Path, target: str | Path) -> object:
        if Path(source).name == "x":
            raise OSError("disk full")
        return real_copy(source, target)

    monkeypatch.setattr(shutil, "copy2", failing_copy)
    failures = migrate(tool_root, moves)

    assert list(failures) == ["config"]
    assert not new.exists()
    assert sorted(p.name for p in tool_root.iterdir()) == [".migrate.lock"]

    monkeypatch.setattr(shutil, "copy2", real_copy)
    assert migrate(tool_root, moves) == {}
    assert (new / "plugins" / "x").exists()


def test_an_empty_destination_folder_is_filled(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    new.mkdir(parents=True)

    assert migrate(tool_root, [(old / "config.toml", new / "config.toml")]) == {}

    assert (new / "config.toml").exists()


def test_a_folder_that_fills_after_the_empty_check_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    new.mkdir(parents=True)
    real_rmdir = os.rmdir

    def filling_rmdir(path: str | Path, dir_fd: int | None = None) -> None:
        if Path(path) == new:
            (new / "mine").write_text("mine", encoding="utf-8")
        real_rmdir(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "rmdir", filling_rmdir)
    failures = migrate(tool_root, [(old / "config.toml", new / "config.toml")])

    assert list(failures) == ["config"]
    assert [p.name for p in new.iterdir()] == ["mine"]


def test_only_its_own_temporary_folder_is_removed(tmp_path: Path) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    other = tool_root / ".config.1-other"
    other.mkdir(parents=True)

    migrate(tool_root, [(old / "config.toml", new / "config.toml")])

    assert other.is_dir()
    assert sorted(p.name for p in tool_root.iterdir()) == [
        ".config.1-other",
        ".migrate.lock",
        "config",
    ]


@pytest.mark.parametrize("kind_of_blocker", ["file", "symlink"])
def test_a_file_or_symlink_at_a_new_folder_is_a_conflict_and_is_kept(
    tmp_path: Path, kind_of_blocker: str
) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    tool_root.mkdir(parents=True)
    if kind_of_blocker == "file":
        new.write_text("mine", encoding="utf-8")
    else:
        new.symlink_to(tmp_path)

    failures = migrate(tool_root, [(old / "config.toml", new / "config.toml")])

    assert list(failures) == ["config"]
    assert unready_kinds(tool_root, [(old / "config.toml", new / "config.toml")]) == {
        "config"
    }
    assert new.is_symlink() == (kind_of_blocker == "symlink")


def test_a_failed_folder_does_not_undo_a_published_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, tool_root, new = _old_and_new(tmp_path)
    other = tool_root / "state"
    (old / "log").write_text("l", encoding="utf-8")
    real_copy = shutil.copy2

    def copy(source: str | Path, target: str | Path) -> object:
        if Path(source).name == "log":
            raise OSError("disk full")
        return real_copy(source, target)

    monkeypatch.setattr(shutil, "copy2", copy)
    failures = migrate(
        tool_root,
        [(old / "config.toml", new / "config.toml"), (old / "log", other / "log")],
    )

    assert list(failures) == ["state"]
    assert (new / "config.toml").exists()
    assert (
        unready_kinds(tool_root, [(old / "config.toml", new / "config.toml")]) == set()
    )
