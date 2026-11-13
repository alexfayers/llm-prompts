from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest

from llm_prompts.benchmark.cell import home_dirs


@pytest.fixture(autouse=True)
def _no_overlay_home_dirs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(home_dirs, "_discover_overlay_paths", lambda quiet: [])
    home_dirs.declared_home_dirs.cache_clear()
    yield
    home_dirs.declared_home_dirs.cache_clear()


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
