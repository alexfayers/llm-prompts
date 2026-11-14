from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from llm_prompts.benchmark import paths
from llm_prompts.benchmark.cell import home_dirs
from llm_prompts.benchmark.runner.process import reset_stop


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture
def live_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "live").mkdir()
    (tmp_path / "roots").mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "live")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "roots"))
    monkeypatch.setattr(paths, "work_dir", lambda: tmp_path / "roots")


def pi_settings_path() -> Path:
    return Path.home() / ".pi" / "agent" / "settings.json"


def give_pi_a_default_model(home: Path) -> None:
    """Write pi settings with a default model into ``home``, as a user's own pi has."""
    path = home / ".pi" / "agent" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"defaultModel": "test-model"}))


@pytest.fixture(autouse=True)
def _pi_default_model(isolated_home: Path) -> None:
    give_pi_a_default_model(isolated_home)


@pytest.fixture(autouse=True)
def _reset_runner_stop() -> None:
    reset_stop()


@pytest.fixture(autouse=True)
def _no_overlay_home_dirs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(home_dirs, "_discover_overlay_paths", lambda quiet: [])
    home_dirs.declared_home_dirs.cache_clear()
    yield
    home_dirs.declared_home_dirs.cache_clear()


@pytest.fixture
def declare_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[dict[str, dict[str, list[str]]]], None]:
    def declare(spec: dict[str, dict[str, list[str]]]) -> None:
        _write_json(tmp_path / "overlay" / home_dirs.HOME_DIRS_FILENAME, spec)
        monkeypatch.setattr(
            home_dirs, "_discover_overlay_paths", lambda quiet: [tmp_path / "overlay"]
        )
        home_dirs.declared_home_dirs.cache_clear()

    return declare


class FakeSandbox:
    def __init__(self) -> None:
        self._present: set[str] = set()

    def present(self, *tools: str) -> None:
        self._present.update(tools)


@pytest.fixture
def fake_sandbox(monkeypatch: pytest.MonkeyPatch) -> FakeSandbox:
    fake = FakeSandbox()
    real = shutil.which

    def which(name: str, *a: object, **k: object) -> str | None:
        if name in ("sandbox-exec", "bwrap"):
            return f"/usr/bin/{name}" if name in fake._present else None
        return real(name)

    monkeypatch.setattr(shutil, "which", which)
    return fake
