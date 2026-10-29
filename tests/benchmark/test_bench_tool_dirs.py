import sys
from pathlib import Path

import pytest

from llm_prompts.benchmark.cell import home_dirs
from llm_prompts.benchmark.cell.home_dirs import HomeDir, link_home_dirs


def test_declared_home_dir_links_and_empties_only_listed_subdirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live, home = tmp_path / "live", tmp_path / "home"
    for sub in ("bin", "state", "secret"):
        (live / ".tools" / sub).mkdir(parents=True)
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: live)

    link_home_dirs(home, {".tools": HomeDir(link=("bin",), empty=("state",))})

    assert not (home / ".tools").is_symlink()
    assert (home / ".tools" / "bin").resolve() == (live / ".tools" / "bin").resolve()
    assert (home / ".tools" / "bin").is_symlink()
    assert list((home / ".tools" / "state").iterdir()) == []
    assert not (home / ".tools" / "secret").exists()


def test_declaring_home_dirs_prints_no_overlay_discovery(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def discover(quiet: bool) -> list[Path]:
        if not quiet:
            print("[*] [overlay] Discovered 'x'", file=sys.stderr)
        return []

    monkeypatch.setattr(home_dirs, "_discover_overlay_paths", discover)

    home_dirs.declared_home_dirs()

    assert capsys.readouterr().err == ""
