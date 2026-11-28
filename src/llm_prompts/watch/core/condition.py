"""Parse watch conditions and test them against polled fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fnmatch import fnmatchcase
from typing import NamedTuple

from .source import Fields, WatchError

CHANGED_PREFIX = "changed:"
LABEL_PREFIX = "label="


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


class LabelCondition(Condition):
    """Holds when a label matching the glob value is added, or is on at the first poll."""

    def matched(self, baseline: Fields, current: Fields) -> bool:
        """Return whether current has a matching label that baseline lacks."""
        before = set() if baseline is current else self._matching(baseline)
        return bool(self._matching(current) - before)

    def _matching(self, fields: Fields) -> set[str]:
        # shortcut: labels are split on commas, so a label name holding a comma never matches.
        names = fields[self.field].split(",")
        return {name for name in names if fnmatchcase(name, self.value or "")}


def parse(text: str, label: str) -> Condition:
    """Parse ``field=value``, ``changed:field`` or ``label=glob``."""
    if text.startswith(LABEL_PREFIX):
        return LabelCondition(label, "labels", text.removeprefix(LABEL_PREFIX))
    if text.startswith(CHANGED_PREFIX):
        return Condition(label, text.removeprefix(CHANGED_PREFIX), None)
    field, separator, value = text.partition("=")
    if not separator or not field:
        raise WatchError(
            f"Invalid condition '{text}'. Use field=value, changed:field or an alias."
        )
    return Condition(label, field, value)


def takes(field: str, values: Sequence[str]) -> str:
    """Describe the values a field takes, as ``ci takes pass, fail or none``."""
    listed = ", ".join(values[:-1]) + " or " if len(values) > 1 else ""
    return f"{field} takes {listed}{values[-1]}"


def expand(
    untils: Sequence[str],
    aliases: Mapping[str, Sequence[str]],
    values: Mapping[str, Sequence[str]],
) -> list[Condition]:
    """Turn each ``--until`` value, or the alias it names, into conditions.

    values maps each field with a fixed set of values to that set, and a condition naming another value is an error.
    """
    try:
        conditions = [
            parse(text, until)
            for until in untils
            for text in aliases.get(until, [until])
        ]
    except WatchError as error:
        raise WatchError(f"{error} Aliases: {', '.join(aliases)}.") from None
    for condition in conditions:
        known = values.get(condition.field)
        if known and condition.value is not None and condition.value not in known:
            raise WatchError(
                f"{takes(condition.field, known)}, not '{condition.value}'."
            )
    return conditions
