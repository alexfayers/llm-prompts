from collections.abc import Callable
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from llm_prompts.benchmark.cell import home_dirs
from llm_prompts.benchmark.cell.home_dirs import HomeDir, link_home_dirs
from llm_prompts.install import _discover_overlay_paths


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


@pytest.fixture
def overlay_package(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    monkeypatch.setattr(home_dirs, "_discover_overlay_paths", _discover_overlay_paths)

    def install(module: str) -> None:
        entry = EntryPoint(name="overlay", value=module, group="llm_prompts")
        monkeypatch.setattr("importlib.metadata.entry_points", lambda group: [entry])

    return install


@pytest.mark.real_prompts
def test_declaring_home_dirs_prints_no_overlay_discovery(
    overlay_package: Callable[[str], None], capsys: pytest.CaptureFixture[str]
) -> None:
    overlay_package("llm_prompts")

    home_dirs.declared_home_dirs()

    assert capsys.readouterr().err == ""


@pytest.mark.real_prompts
def test_declaring_home_dirs_reports_an_overlay_that_fails_to_load(
    overlay_package: Callable[[str], None], capsys: pytest.CaptureFixture[str]
) -> None:
    overlay_package("missing_overlay_package")

    home_dirs.declared_home_dirs()

    assert "Failed to load 'overlay'" in capsys.readouterr().err
