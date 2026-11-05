"""Parse watch conditions and test them against polled fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NamedTuple

from .source import Fields, WatchError

CHANGED_PREFIX = "changed:"


class Condition(NamedTuple):
    """One test: a field equals a value, or a field differs from its first poll."""

    label: str
    field: str
    value: str | None

    def matched(self, baseline: Fields, current: Fields) -> bool:
        """Return whether the current fields satisfy this condition."""
        if self.value is None:
            return current[self.field] != baseline[self.field]
        return current[self.field] == self.value


def parse(text: str, label: str) -> Condition:
    """Parse ``field=value`` or ``changed:field``."""
    if text.startswith(CHANGED_PREFIX):
        return Condition(label, text.removeprefix(CHANGED_PREFIX), None)
    field, separator, value = text.partition("=")
    if not separator or not field:
        raise WatchError(
            f"Invalid condition '{text}'. Use field=value, changed:field or an alias."
        )
    return Condition(label, field, value)


def expand(
    untils: Sequence[str], aliases: Mapping[str, Sequence[str]]
) -> list[Condition]:
    """Turn each ``--until`` value, or the alias it names, into conditions."""
    try:
        return [
            parse(text, until)
            for until in untils
            for text in aliases.get(until, [until])
        ]
    except WatchError as error:
        raise WatchError(f"{error} Aliases: {', '.join(aliases)}.") from None
