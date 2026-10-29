"""Tests for MCP tool exclusion."""

from __future__ import annotations

from http.client import IncompleteRead
from typing import Any

import pytest

from llm_prompts import mcp

URL = "http://mcp.test/mcp"


@pytest.mark.parametrize(
    ("failures", "excluded", "warns"), [(1, "put", False), (2, "*", True)]
)
def test_excluded_tools_retries_a_truncated_read_once(
    monkeypatch: pytest.MonkeyPatch, failures: int, excluded: str, warns: bool
) -> None:
    calls = 0

    def flaky_tools(url: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls <= failures:
            raise IncompleteRead(b"")
        return [{"name": "put"}]

    warnings: list[str] = []
    monkeypatch.setattr(mcp, "_tools", flaky_tools)

    result = mcp._excluded_tools("m_x", {"url": URL}, mcp.PI_NAMING, warnings.append)

    assert result == (f"mcp__m_x__{excluded}",)
    assert bool(warnings) is warns
