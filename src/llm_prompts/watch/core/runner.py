"""Poll a source until a condition holds."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence

from .condition import Condition, expand, parse
from .source import Fields, Source, Stateful, WatchError
from .store import Persisted

EXIT_TIMEOUT = 124


def _timeout_text(fields: Fields) -> str:
    inline = " ".join(f"{n}={v}" for n, v in fields.items() if "\n" not in v)
    blocks = [v for v in fields.values() if "\n" in v]
    return "\n".join([f"timeout ({inline})", *blocks])


def _describe(condition: Condition, current: Fields) -> str:
    value = current[condition.field]
    if "\n" in value:
        return f"{condition.label}\n{value}"
    detail = f"{condition.field}={value}"
    if condition.label == detail:
        return detail
    return f"{condition.label} ({detail})"


Discover = Callable[[], Sequence[Source]]


def _poll_until_done(
    initial: Sequence[Source],
    untils: list[str],
    interval: float | None,
    timeout: float | None,
    require_all: bool,
    follow: bool,
    discover: Discover | None = None,
) -> int:
    sources: list[Source] = []
    terminals: list[list[Condition]] = []
    conditions: list[list[Condition]] = []

    def add(found: Sequence[Source]) -> list[int]:
        added = []
        for found_source in found:
            source = (
                Persisted(found_source)
                if isinstance(found_source, Stateful)
                else found_source
            )
            terminal = (
                [parse(text, text) for text in getattr(source, "terminal", ())]
                if follow
                else []
            )
            added.append(len(sources))
            sources.append(source)
            terminals.append(terminal)
            conditions.append(expand(untils, source.aliases) + terminal)
        return added

    waiting = add(initial)
    start = time.time()
    stop = None if timeout is None else start + timeout
    baselines: dict[int, Fields] = {}
    currents: dict[int, Fields] = {}
    reported: dict[int, Fields] = {}
    while True:
        if discover:
            watched = {sources[index].describe() for index in waiting}
            waiting += add([s for s in discover() if s.describe() not in watched])
        for index in waiting[:]:
            current = currents[index] = sources[index].poll()
            if index not in baselines:
                baselines[index] = current
                for condition in conditions[index]:
                    if condition.field not in current:
                        raise WatchError(
                            f"Unknown field '{condition.field}'. Fields: {', '.join(current)}."
                        )
            for condition in conditions[index]:
                if condition.matched(baselines[index], current):
                    if follow and reported.get(index) == current:
                        break
                    print(
                        f"{sources[index].describe()}: {_describe(condition, current)}",
                        flush=True,
                    )
                    if follow and not any(
                        terminal.matched(current, current)
                        for terminal in terminals[index]
                    ):
                        baselines[index] = reported[index] = current
                    else:
                        waiting.remove(index)
                    break
            else:
                reported.pop(index, None)
                baselines[index] = current
            if not require_all and not follow and index not in waiting:
                return 0
        if not waiting and not discover:
            return 0
        now = time.time()
        if stop is not None and now >= stop:
            for index in waiting:
                print(
                    f"{sources[index].describe()}: {_timeout_text(currents[index])}",
                    flush=True,
                )
            return EXIT_TIMEOUT
        pause = sources[0].default_interval if interval is None else interval
        time.sleep(pause if stop is None else min(pause, stop - now))


def watch(
    sources: Sequence[Source],
    untils: list[str],
    *,
    interval: float | None,
    timeout: float | None,
    require_all: bool = False,
    follow: bool = False,
    discover: Discover | None = None,
) -> int:
    """Poll until any source, or every source with require_all, matches, and return the exit code.

    With follow, print each match once per change, reset its baseline and keep polling until the timeout
    or a state in the source's optional ``terminal`` conditions.
    With discover, call it before each poll and add the sources it returns that are new, so the watch never ends on its own.
    """
    try:
        return _poll_until_done(
            sources, untils, interval, timeout, require_all, follow, discover
        )
    except WatchError as error:
        print(f"watch: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"watch: unexpected error: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
    return 1
