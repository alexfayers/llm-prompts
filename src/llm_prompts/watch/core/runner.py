"""Poll a source until a condition holds."""

from __future__ import annotations

import sys
import time

from .condition import expand
from .source import Fields, Source, WatchError

EXIT_TIMEOUT = 124


def _format(fields: Fields) -> str:
    return " ".join(f"{name}={value}" for name, value in fields.items())


def _poll_until_done(
    source: Source,
    untils: list[str],
    interval: float | None,
    timeout: float | None,
) -> int:
    conditions = expand(untils, source.aliases)
    start = time.time()
    baseline = current = source.poll()
    for condition in conditions:
        if condition.field not in baseline:
            raise WatchError(
                f"Unknown field '{condition.field}'. Fields: {', '.join(baseline)}."
            )
    stop = None if timeout is None else start + timeout
    while True:
        for condition in conditions:
            if condition.matched(baseline, current):
                detail = f"{condition.field}={current[condition.field]}"
                print(
                    f"{source.describe()}: "
                    + (
                        condition.label
                        if condition.label == detail
                        else f"{condition.label} ({detail})"
                    )
                )
                return 0
        now = time.time()
        if stop is not None and now >= stop:
            print(f"{source.describe()}: timeout ({_format(current)})")
            return EXIT_TIMEOUT
        pause = source.default_interval if interval is None else interval
        time.sleep(pause if stop is None else min(pause, stop - now))
        current = source.poll()


def watch(
    source: Source,
    untils: list[str],
    *,
    interval: float | None,
    timeout: float | None,
) -> int:
    """Poll until a condition matches, printing one line, and return the exit code."""
    try:
        return _poll_until_done(source, untils, interval, timeout)
    except WatchError as error:
        print(f"watch: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"watch: unexpected error: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
    return 1
