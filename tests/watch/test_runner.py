"""Tests for watching several sources at once."""

from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar

import pytest

from llm_prompts.watch.core import runner
from llm_prompts.watch.core.runner import watch
from llm_prompts.watch.core.source import Fields


class StubSource:
    default_interval = 0.0
    aliases: ClassVar[dict[str, list[str]]] = {}

    def __init__(self, label: str, *states: str) -> None:
        self.label, self.states, self.state = label, iter(states), ""

    def describe(self) -> str:
        return self.label

    def poll(self) -> Fields:
        self.state = next(self.states, self.state)
        return {"state": self.state}


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


@pytest.mark.parametrize(
    ("until", "states", "expected"),
    [
        (
            "changed:state",
            ("x", "y", "y", "z"),
            ["a: changed:state (state=y)", "a: changed:state (state=z)"],
        ),
        ("state=done", ("x", "done", "done", "x", "done"), ["a: state=done"] * 2),
    ],
)
def test_watch_follow_prints_each_change_once_and_exits_only_on_timeout(
    capsys: pytest.CaptureFixture[str],
    until: str,
    states: tuple[str, ...],
    expected: list[str],
) -> None:
    source = StubSource("a", *states)

    assert watch([source], [until], interval=0, timeout=0.05, follow=True) == 124
    assert capsys.readouterr().out.splitlines()[:-1] == expected


class CrLikeSource:
    default_interval = 0.0
    aliases: ClassVar[dict[str, list[str]]] = {
        "merged": ["merged=true"],
        "update": ["changed:approvals"],
    }
    terminal: ClassVar[list[str]] = ["merged=true"]

    def __init__(self, *states: tuple[str, str]) -> None:
        self.states, self.state = iter(states), states[0]

    def describe(self) -> str:
        return "cr"

    def poll(self) -> Fields:
        self.state = next(self.states, self.state)
        return dict(zip(("approvals", "merged"), self.state, strict=True))


@pytest.mark.parametrize(
    ("untils", "expected"),
    [
        (
            ["update", "merged"],
            ["cr: update (approvals=a)", "cr: merged (merged=true)"],
        ),
        (["update"], ["cr: update (approvals=a)", "cr: merged=true"]),
    ],
)
def test_watch_follow_exits_after_printing_a_terminal_state(
    capsys: pytest.CaptureFixture[str], untils: list[str], expected: list[str]
) -> None:
    states = [("", "false"), ("a", "false"), ("a", "false"), ("a", "true")]
    source = CrLikeSource(*states)

    assert watch([source], untils, interval=0, timeout=5, follow=True) == 0
    assert capsys.readouterr().out.splitlines() == expected


def test_watch_follow_keeps_watching_until_every_source_is_terminal(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Counting(CrLikeSource):
        polls = 0

        def poll(self) -> Fields:
            Counting.polls += 1
            return super().poll()

    done = CrLikeSource(("", "false"), ("a", "true"))
    open_ = Counting(("", "false"), ("", "false"), ("", "false"), ("b", "false"))
    clock = SimpleNamespace(time=lambda: float(Counting.polls), sleep=lambda _: None)
    monkeypatch.setattr(runner, "time", clock)

    assert watch([done, open_], ["update"], interval=0, timeout=4, follow=True) == 124
    assert capsys.readouterr().out.splitlines()[:-1] == [
        "cr: update (approvals=a)",
        "cr: update (approvals=b)",
    ]


def test_watch_discover_rejoins_a_source_that_ended_and_is_listed_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Ending(StubSource):
        terminal: ClassVar[list[str]] = ["state=closed"]

    runs = iter(
        [[Ending("pr", "open", "closed")], [], [Ending("pr", "open", "closed")]]
    )

    def listed() -> list[Ending]:
        return next(runs, [])

    watch([], ["changed:state"], interval=0, timeout=0.2, follow=True, discover=listed)

    assert capsys.readouterr().out.count("pr: ") == 2
