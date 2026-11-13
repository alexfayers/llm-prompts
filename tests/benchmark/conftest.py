from __future__ import annotations

from collections.abc import Iterator

import pytest

from llm_prompts.benchmark.cell import home_dirs


@pytest.fixture(autouse=True)
def _no_overlay_home_dirs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(home_dirs, "_discover_overlay_paths", lambda quiet: [])
    home_dirs.declared_home_dirs.cache_clear()
    yield
    home_dirs.declared_home_dirs.cache_clear()
