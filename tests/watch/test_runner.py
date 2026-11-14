"""Tests for watching several sources at once."""

from __future__ import annotations

from typing import ClassVar

import pytest

from llm_prompts.watch.core.runner import watch
from llm_prompts.watch.core.source import Fields


class StubSource:
    default_interval = 0.0
    aliases: ClassVar[dict[str, list[str]]] = {}

    def __init__(self, label: str, *states: str) -> None:
        self.label, self.states = label, iter(states)

    def describe(self) -> str:
        return self.label

    def poll(self) -> Fields:
        return {"state": next(self.states)}


def test_watch_stops_when_any_source_matches(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sources = [StubSource("a", "x", "x"), StubSource("b", "x", "done")]

    assert watch(sources, ["state=done"], interval=0, timeout=5) == 0
    assert capsys.readouterr().out == "b: state=done\n"


def test_watch_with_require_all_waits_for_every_source(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sources = [StubSource("a", "x", "done"), StubSource("b", "x", "x", "done")]

    assert watch(sources, ["state=done"], interval=0, timeout=5, require_all=True) == 0
    assert capsys.readouterr().out == "a: state=done\nb: state=done\n"


def test_watch_stops_on_an_early_match_before_polling_a_failing_source() -> None:
    sources = [StubSource("a", "done"), StubSource("b")]

    assert watch(sources, ["state=done"], interval=0, timeout=5) == 0
