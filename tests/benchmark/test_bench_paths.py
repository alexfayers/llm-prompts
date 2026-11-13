from pathlib import Path

import pytest

from llm_prompts.benchmark import paths


def test_work_dir_avoids_a_ram_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mounts = tmp_path / "mounts"
    mounts.write_text(f"tmpfs {tmp_path / 'ram'} tmpfs rw 0 0\n")
    (tmp_path / "ram").mkdir()
    (tmp_path / "disk").mkdir()
    monkeypatch.setattr(paths, "MOUNT_TABLE", mounts)

    monkeypatch.setenv("TMPDIR", str(tmp_path / "ram"))
    assert paths.work_dir() == paths.cache_dir() / "cells"

    monkeypatch.setenv("TMPDIR", str(tmp_path / "disk"))
    assert paths.work_dir() == tmp_path / "disk" / paths.WORK_DIR_NAME
