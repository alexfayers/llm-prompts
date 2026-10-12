"""Compares prompt sizes between a base and the current checkout.

Both sides are rendered with HEAD's code, so changes to the renderer itself
are not reflected in the report - only changes to the prompt sources and
variables.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .cli import _size_guard_roots
from .size_guard import CHECKED_TARGETS, Artifact, ceiling_for, check
from .size_limits import (
    ALWAYS_AGENT_FRONTMATTER_BYTES,
    ALWAYS_RULE_BYTES,
    ALWAYS_SKILL_FRONTMATTER_BYTES,
    BYTES_PER_TOKEN,
    COLLECTION_BYTES,
    ON_DEMAND_AGENT_BODY_BYTES,
    ON_DEMAND_ROLE_RULE_BYTES,
    ON_DEMAND_SKILL_BODY_BYTES,
    ON_DEMAND_WORKFLOW_BYTES,
    START_BYTES,
)


@dataclass(frozen=True)
class Row:
    """One measured size compared across base and head.

    Args:
        metric: Metric identifier from `size_limits.py`.
        targets: Render targets sharing these values.
        name: Installed name when the source path does not already show it,
            else empty.
        file: Source path relative to its prompts root.
        base: Base value, or None if the artifact is new.
        head: Head value, or None if the artifact was removed.
        ceiling: Ceiling in force at head (base if removed), or None.
    """

    metric: str
    targets: tuple[str, ...]
    name: str
    file: str
    base: int | None
    head: int | None
    ceiling: int | None

    @property
    def delta(self) -> int:
        """Head minus base, counting a missing side as zero."""
        return (self.head or 0) - (self.base or 0)

    @property
    def pct(self) -> float | None:
        """Delta as a percentage of base, or None without both sides."""
        if not self.base or self.head is None:
            return None
        return self.delta / self.base * 100

    @property
    def over(self) -> bool:
        """Whether head exceeds its ceiling."""
        return (
            self.head is not None
            and self.ceiling is not None
            and self.head > self.ceiling
        )


_Key = tuple[str, str, str]
_Values = tuple[str, str, str, int | None, int | None, int | None]
_SMALLER = "&#x1F7E2;"
_LARGER = "&#x1F534;"
_NEW = "&#x1F195;"
_REMOVED = "&#x1F5D1;&#xFE0F;"
_UNCHANGED = "&#x26AA;"
_OVER_LIMIT = "&#x26A0;&#xFE0F;"
_BADGE_ESCAPES = str.maketrans(
    {"-": "--", "_": "__", " ": "_", "%": "%25", "+": "%2B", "<": "%3C"}
)
_ALIGNMENT = {
    "": ":-:",
    "target": "---",
    "file": "---",
    "metric": "---",
    "targets": "---",
}
_COLUMN_METRICS = {
    "rules": (ALWAYS_RULE_BYTES,),
    "frontmatter": (ALWAYS_SKILL_FRONTMATTER_BYTES, ALWAYS_AGENT_FRONTMATTER_BYTES),
    "bodies": (ON_DEMAND_SKILL_BODY_BYTES, ON_DEMAND_WORKFLOW_BYTES),
    "agent bodies": (ON_DEMAND_AGENT_BODY_BYTES,),
    "role-only rules": (ON_DEMAND_ROLE_RULE_BYTES,),
    "start": (START_BYTES,),
    "worst case": (COLLECTION_BYTES,),
}
_COLUMN_OF = {
    metric: column for column, metrics in _COLUMN_METRICS.items() for metric in metrics
}
_SUMMARY_COLUMNS = ("rules", "frontmatter", "bodies", "start", "worst case")
_SIZE_COLUMNS = frozenset({"start", "worst case"})
_SUMMARY_HEADER = ["", "target", *_SUMMARY_COLUMNS]
_DETAIL_HEADER = ["", "target", *_COLUMN_METRICS]
_ROW_HEADER = [
    "",
    "file",
    "metric",
    "targets",
    "before",
    "after",
    "change",
    "%",
    "limit",
]


def _numeric(artifacts: Iterable[Artifact]) -> dict[_Key, Artifact]:
    return {
        (a.metric, a.target, a.dest_name): a
        for a in artifacts
        if not isinstance(a.value, bool)
    }


def _relative(source: Path, roots: Sequence[Path]) -> str:
    root = next(r for r in roots if source.is_relative_to(r))
    relative = source.relative_to(root)
    if relative == Path():
        return "-"
    return f"{relative}" if root == roots[0] else f"{root.parent.name}:{relative}"


def _variant(name: str, source: Path) -> str:
    return "" if name.split(".")[0] in {source.stem, source.parent.name} else name


def compare(
    base_artifacts: Iterable[Artifact],
    head_artifacts: Iterable[Artifact],
    base_roots: Sequence[Path],
    head_roots: Sequence[Path],
) -> list[Row]:
    """Join base and head measurements into one row per artifact.

    Args:
        base_artifacts: Artifacts measured on the base.
        head_artifacts: Artifacts measured on head.
        base_roots: Prompts directories the base was measured under.
        head_roots: Prompts directories head was measured under.

    Returns:
        One row per (metric, target, name) present on either side.
    """
    base = _numeric(base_artifacts)
    head = _numeric(head_artifacts)
    targets_by_values: dict[_Values, list[str]] = {}
    for key in [*head, *(k for k in base if k not in head)]:
        metric, target, name = key
        base_artifact, head_artifact = base.get(key), head.get(key)
        artifact = head_artifact or base_artifact
        assert artifact is not None
        values = (
            metric,
            _variant(name, artifact.source),
            _relative(artifact.source, head_roots if head_artifact else base_roots),
            None if base_artifact is None else int(base_artifact.value),
            None if head_artifact is None else int(head_artifact.value),
            ceiling_for(artifact),
        )
        targets_by_values.setdefault(values, []).append(target)
    return [
        Row(values[0], tuple(targets), *values[1:])
        for values, targets in targets_by_values.items()
    ]


def _signed(value: int) -> str:
    return f"{value:+,}" if value else "0"


def _pct(row: Row) -> str:
    if row.base is None:
        return "new"
    if row.head is None:
        return "removed"
    if row.pct is None:
        return "-"
    if not row.delta:
        return "0%"
    return "<0.1%" if abs(row.pct) < 0.05 else f"{row.pct:+.1f}%"


def _trend(delta: int) -> str:
    if delta < 0:
        return _SMALLER
    return _LARGER if delta else _UNCHANGED


def _badge(target: str, row: Row) -> str:
    colour = "brightgreen" if row.delta < 0 else "red" if row.delta else "lightgrey"
    label, message = (text.translate(_BADGE_ESCAPES) for text in (target, _pct(row)))
    return f"![{target}](https://img.shields.io/badge/{label}-{message}-{colour})"


def _emoji(row: Row) -> str:
    if row.over:
        return _OVER_LIMIT
    if row.base is None:
        return _NEW
    if row.head is None:
        return _REMOVED
    return _trend(row.delta)


def _count(value: int | None) -> str:
    return "-" if value is None else f"{value:,}"


def _line(cells: Iterable[str]) -> str:
    return "|" + "|".join(f" {cell} " if cell else " " for cell in cells) + "|"


def _table(header: Sequence[str], lines: Iterable[Sequence[str]]) -> list[str]:
    return [
        _line(header),
        _line(_ALIGNMENT.get(column, "---:") for column in header),
        *map(_line, lines),
    ]


def _targets(targets: Sequence[str]) -> str:
    return "all" if set(targets) == set(CHECKED_TARGETS) else ", ".join(targets)


def _file(row: Row) -> str:
    root, separator, path = row.file.rpartition(":")
    file = f"{root}{separator}{path.removeprefix('shared/')}"
    if row.metric == COLLECTION_BYTES or not row.name:
        return file
    return f"{file} ({row.name})"


def _row_lines(rows: Iterable[Row]) -> list[list[str]]:
    return [
        [
            _emoji(row),
            _file(row),
            row.metric,
            _targets(row.targets),
            _count(row.base),
            _count(row.head),
            *(
                ["", ""]
                if row.base is None or row.head is None
                else [_signed(row.delta), _pct(row)]
            ),
            _count(row.ceiling),
        ]
        for row in rows
    ]


_Sizes = dict[str, dict[str, list[int]]]


def _cell(before_after: Sequence[int] | None) -> str:
    if before_after is None or before_after[0] == before_after[1]:
        return "-"
    before, after = before_after
    return f"{before:,} -> {after:,} ({_signed(after - before)})"


def _change_cell(before_after: Sequence[int] | None) -> str:
    if before_after is None or before_after[0] == before_after[1]:
        return "-"
    return _signed(before_after[1] - before_after[0])


def _size_cell(pairs: Sequence[Sequence[int] | None]) -> str:
    first = pairs[0]
    if first is None or first[0] == first[1]:
        return "-"
    if any(pair is None or pair[1] != first[1] for pair in pairs):
        return _change_cell(first)
    pct = _pct(Row("", (), "", "", first[0], first[1], None))
    size = f"{first[1]:,} ({pct})" if first[0] else f"{first[1]:,}"
    return f"{size}<br>~{first[1] / BYTES_PER_TOKEN / 1000:.1f}k tok"


def _sizes_by_target(rows: Iterable[Row]) -> _Sizes:
    sizes: _Sizes = {}
    for row in rows:
        for target in row.targets:
            pair = sizes.setdefault(target, {}).setdefault(
                _COLUMN_OF[row.metric], [0, 0]
            )
            pair[0] += row.base or 0
            pair[1] += row.head or 0
    return sizes


def _changed(columns: dict[str, list[int]], names: Iterable[str]) -> bool:
    return any(
        columns[name][0] != columns[name][1] for name in names if name in columns
    )


def _summary_lines(sizes: _Sizes, totals: dict[str, Row]) -> list[list[str]]:
    groups: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for target, columns in sizes.items():
        if not _changed(columns, _SUMMARY_COLUMNS):
            continue
        key = (
            _emoji(totals[target]) if target in totals else _UNCHANGED,
            tuple(_change_cell(columns.get(name)) for name in _SUMMARY_COLUMNS),
        )
        groups.setdefault(key, []).append(target)
    return [
        [
            emoji,
            ", ".join(targets),
            *(
                _size_cell([sizes[t].get(name) for t in targets])
                if name in _SIZE_COLUMNS
                else change
                for name, change in zip(_SUMMARY_COLUMNS, changes, strict=True)
            ),
        ]
        for (emoji, changes), targets in groups.items()
    ]


def _detail_lines(sizes: _Sizes, totals: dict[str, Row]) -> list[list[str]]:
    return [
        [
            _emoji(totals[target]) if target in totals else _UNCHANGED,
            target,
            *(_cell(columns.get(name)) for name in _COLUMN_METRICS),
        ]
        for target, columns in sizes.items()
        if _changed(columns, _COLUMN_METRICS)
    ]


def _details(summary: str, table: list[str]) -> str:
    body = "\n".join(table)
    return f"<details>\n<summary>{summary}</summary>\n\n{body}\n\n</details>"


def render_markdown(rows: Sequence[Row]) -> str:
    """Render the comparison as a markdown PR comment body.

    Args:
        rows: Rows from `compare`.

    Returns:
        Markdown with per-target badges, a changed-file headline, one summary
        table of the targets whose size changed, and a collapsed table of the
        changed files.
    """
    collection = [row for row in rows if row.metric == COLLECTION_BYTES]
    sizes = _sizes_by_target(row for row in rows if row.metric in _COLUMN_OF)
    totals = {target: row for row in collection for target in row.targets}
    changed = sorted(
        (r for r in rows if r.metric not in _COLUMN_OF and r.delta),
        key=lambda r: -abs(r.delta),
    )
    badges = " ".join(
        _badge(target, row) for row in collection for target in row.targets
    )
    changed_files = {row.file for row in changed}
    headline = (
        f"**Prompt size** {_trend(sum(row.delta for row in changed))} "
        f"{len(changed_files)} {'file' if len(changed_files) == 1 else 'files'} "
        f"changed size in this PR, "
        f"{len({row.file for row in changed if row.over})} over the limit"
    )
    if not changed:
        return f"{badges}\n\n{headline}\n\nThis PR changes no prompt sizes.\n"
    sections = [
        badges,
        headline,
        "\n".join(_table(_SUMMARY_HEADER, _summary_lines(sizes, totals))),
        _details("Details", _table(_DETAIL_HEADER, _detail_lines(sizes, totals))),
        _details("Changed files", _table(_ROW_HEADER, _row_lines(changed))),
    ]
    return "\n\n".join(sections) + "\n"


def build_report(base_prompts: Path) -> str:
    """Measure base and head and render the comparison.

    Args:
        base_prompts: The base revision's own prompts directory.

    Returns:
        A markdown report, or a note that there is no base to compare against.
    """
    if not base_prompts.is_dir():
        return (
            "## Prompt size report\n\n"
            f"No base prompts at `{base_prompts}` to compare against.\n"
        )
    head_roots = _size_guard_roots()
    base_roots = [base_prompts, *head_roots[1:]]
    head = check(head_roots)
    base = check(base_roots, vars_root=base_prompts)
    return render_markdown(
        compare(base.artifacts, head.artifacts, base_roots, head_roots)
    )
