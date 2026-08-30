"""Measures installed-artifact sizes against `size_limits.py`'s thresholds.

Every measurement replicates the render-vs-linked dispatch `install.py` itself
uses (`_collect_content_srcs`'s `agent_specific` flag): shared sources are
rendered with variables substituted, agent-specific sources are only stripped
of their gating keys. Calling a per-target render function directly, or
re-implementing that dispatch, understates measurements and is exactly the
class of bug this guard exists to catch.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from .install import (
    _Agent,
    _builtin_skill_vars,
    _collect_content_srcs,
    _CopilotAgent,
    _excluded_targets,
    _expand_agent_variants,
    _linked_content,
    _passes_requires_gate,
    _read_text,
    _rendered_content,
    _resolve_priority_sources,
)
from .render_template import (
    find_unreplaced_variables,
    parse_frontmatter,
    resolve_frontmatter,
    split_frontmatter,
    substitute_variables,
)
from .size_limits import (
    AGENT_DESCRIPTION_CHARS,
    FINALS,
    FRONTMATTER_VALID,
    NO_UNSUBSTITUTED_PLACEHOLDERS,
    RULE_BYTES,
    RULE_LINES,
    SCHEDULES,
    SKILL_BODY_BYTES,
    SKILL_DESCRIPTION_CHARS,
    UNITS,
    WORKFLOW_BYTES,
    WORKFLOW_LINES,
)

CHECKED_TARGETS: tuple[str, ...] = ("claude-code", "copilot", "kiro")
ALLOWANCES_FILENAME = "size_allowances.json"


@dataclass(frozen=True)
class Artifact:
    """One measured value for one installed artifact.

    Args:
        metric: Metric identifier from `size_limits.py`.
        target: Render target this measurement is for.
        dest_name: Installed destination filename or skill/agent name.
        value: Measured value - an int for size metrics, a bool for the
            unconditional frontmatter/placeholder checks.
        source: Source file path, for failure reporting.
        allowance: Declared per-artifact ceiling from the owning root's
            `size_allowances.json`, or None if undeclared.
    """

    metric: str
    target: str
    dest_name: str
    value: int | bool
    source: Path
    allowance: int | None = None


@dataclass(frozen=True)
class Violation:
    """One artifact that failed its metric's ceiling."""

    metric: str
    target: str
    dest_name: str
    actual: int | bool
    threshold: int | bool
    source: Path


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a full `check()` run."""

    passed: bool
    artifacts: list[Artifact]
    violations: list[Violation]
    report: str
    declaration_errors: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)


def _own_root_dir() -> Path:
    """Return this package's own prompts directory.

    Variables are always resolved from here, regardless of which `roots` are
    being scanned - an overlay's own prompts directory never ships its own
    `vars.json`, matching how `install.main()` renders overlay content with
    the consuming package's variables.

    Returns:
        Path to `llm_prompts`'s own `prompts` directory.
    """
    return Path(str(files("llm_prompts") / "prompts"))


def _own_vars_path(target: str) -> Path:
    """Return this package's own variables JSON path for a target."""
    return _own_root_dir() / target / "vars.json"


def _agent_for(target: str, root: Path) -> _Agent:
    """Build a throwaway `_Agent` scoped to `root`, for dispatch/name lookups only.

    Only used to drive `_collect_content_srcs`'s dest-name mapping and
    agent-specific source discovery under `root` - never installed, so its
    `dirs` mapping is unused and left empty.

    Args:
        target: Target agent name.
        root: Prompts directory to scope this agent to.

    Returns:
        A `_Agent` (or `_CopilotAgent` for copilot) rooted at `root`.
    """
    if target == "copilot":
        return _CopilotAgent(name=target, root_dir=root, dirs={})
    return _Agent(name=target, root_dir=root, dirs={})


def _resolve_content_frontmatter(
    content: str,
) -> tuple[str, dict[str, str], bool]:
    """Split and resolve a content string's frontmatter, folding block scalars.

    Args:
        content: File content that may begin with a frontmatter block.

    Returns:
        A ``(body, resolved_frontmatter, frontmatter_valid)`` triple. Content
        with no frontmatter block resolves to an empty mapping and is valid.
    """
    split = split_frontmatter(content)
    if split is None:
        return content, {}, True
    frontmatter_lines, body = split
    resolved = resolve_frontmatter(frontmatter_lines)
    return body, (resolved or {}), resolved is not None


def _common_artifacts(
    content: str, metric_prefix_target: str, dest_name: str, source: Path
) -> Iterator[Artifact]:
    """Yield the unconditional frontmatter-validity/placeholder checks for content.

    Args:
        content: Fully rendered/substituted/linked content, as installed.
        metric_prefix_target: Target name to record on the yielded artifacts.
        dest_name: Installed destination name.
        source: Source file path.
    """
    _, _, frontmatter_valid = _resolve_content_frontmatter(content)
    yield Artifact(
        FRONTMATTER_VALID, metric_prefix_target, dest_name, frontmatter_valid, source
    )
    yield Artifact(
        NO_UNSUBSTITUTED_PLACEHOLDERS,
        metric_prefix_target,
        dest_name,
        not find_unreplaced_variables(content),
        source,
    )


def _declared_allowances(root: Path) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Load and validate one root's declared per-artifact size allowances.

    Args:
        root: Prompts directory whose `size_allowances.json` to load.

    Returns:
        A ``(allowances, errors)`` pair. `allowances` maps metric to
        dest_name to ceiling; a metric with any error contributes no
        allowances. `errors` are human-readable lines naming the file.
    """
    path = root / ALLOWANCES_FILENAME
    if not path.is_file():
        return {}, []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {}, [f"{path}: could not parse JSON: {e}"]

    allowances: dict[str, dict[str, int]] = {}
    errors: list[str] = []
    for metric, entries in raw.items():
        if metric not in FINALS:
            errors.append(f"{path}: unknown metric '{metric}'")
            continue
        if not isinstance(entries, dict):
            errors.append(f"{path}: '{metric}' must map dest names to ceilings")
            continue
        metric_errors = []
        resolved: dict[str, int] = {}
        for dest_name, ceiling in entries.items():
            if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling <= 0:
                metric_errors.append(
                    f"{path}: '{metric}.{dest_name}' must be a positive int, "
                    f"got {ceiling!r}"
                )
                continue
            resolved[dest_name] = ceiling
        if metric_errors:
            errors.extend(metric_errors)
            continue
        allowances[metric] = resolved
    return allowances, errors


def _iter_rendered_kind_artifacts(
    root: Path,
    target: str,
    subdir: str,
    bytes_metric: str,
    lines_metric: str,
    allowances: dict[str, dict[str, int]],
) -> Iterator[Artifact]:
    """Yield size/validity artifacts for one rules/workflows subdir.

    Replicates `_collect_content_srcs`'s dispatch exactly: shared sources are
    rendered with variables substituted, agent-specific sources are only
    stripped of gating keys.

    Args:
        root: Prompts directory being scanned.
        target: Render target.
        subdir: Content subdirectory (``"rules"`` or ``"workflows"``).
        bytes_metric: Metric identifier for the byte-count measurement.
        lines_metric: Metric identifier for the line-count measurement.
        allowances: This root's declared per-artifact ceilings.
    """
    agent = _agent_for(target, root)
    shared_src = root / "shared" / subdir
    vars_path = _own_vars_path(target)

    for dest_name, src, agent_specific in _collect_content_srcs(
        agent, subdir, shared_src, [], []
    ):
        content = (
            _linked_content(src)
            if agent_specific
            else _rendered_content(src, vars_path, target)
        )
        yield Artifact(
            bytes_metric,
            target,
            dest_name,
            len(content.encode()),
            src,
            allowances.get(bytes_metric, {}).get(dest_name),
        )
        yield Artifact(
            lines_metric,
            target,
            dest_name,
            len(content.splitlines()),
            src,
            allowances.get(lines_metric, {}).get(dest_name),
        )
        yield from _common_artifacts(content, target, dest_name, src)


def _iter_skill_artifacts(
    root: Path, target: str, allowances: dict[str, dict[str, int]]
) -> Iterator[Artifact]:
    """Yield size/validity artifacts for shared and per-target skills.

    Skills never split by shared-vs-agent-specific the way rules/workflows do
    - every skill's `SKILL.md` is substituted (never rendered), matching
    `_materialize_builtin_skill`.

    Args:
        root: Prompts directory being scanned.
        target: Render target.
        allowances: This root's declared per-artifact ceilings.
    """
    candidate_dirs = [root / "shared" / "skills", root / target / "skills"]
    variables = _builtin_skill_vars(_own_vars_path(target))

    def gate(skill_dir: Path) -> bool:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            return False
        if not _passes_requires_gate(skill_md):
            return False
        return target not in _excluded_targets(skill_md)

    resolved = _resolve_priority_sources(
        candidate_dirs,
        lambda d: [p for p in sorted(d.iterdir()) if p.is_dir()],
        lambda p: p.name,
        gate,
    )
    for name, skill_dir in resolved:
        skill_md = skill_dir / "SKILL.md"
        substituted = substitute_variables(_read_text(skill_md), variables)
        # `parse_frontmatter`'s body drops the blank line separating it from
        # the frontmatter block, matching what the metric intends to measure.
        body, _ = parse_frontmatter(substituted)
        _, frontmatter, _ = _resolve_content_frontmatter(substituted)
        yield Artifact(
            SKILL_BODY_BYTES,
            target,
            name,
            len(body.encode()),
            skill_md,
            allowances.get(SKILL_BODY_BYTES, {}).get(name),
        )
        yield Artifact(
            SKILL_DESCRIPTION_CHARS,
            target,
            name,
            len(frontmatter.get("description", "")),
            skill_md,
            allowances.get(SKILL_DESCRIPTION_CHARS, {}).get(name),
        )
        yield from _common_artifacts(substituted, target, name, skill_md)


def _iter_agent_artifacts(
    root: Path, target: str, allowances: dict[str, dict[str, int]]
) -> Iterator[Artifact]:
    """Yield post-expansion description/validity artifacts for claude-code agents.

    A `generate_variants` source is measured once per generated variant, since
    that is what actually gets installed; any other source is measured as
    installed verbatim (a plain symlink, per `_install_agents`).

    Args:
        root: Prompts directory being scanned.
        target: Render target - agents are claude-code only.
        allowances: This root's declared per-artifact ceilings.
    """
    if target != "claude-code":
        return
    agents_dir = root / "claude-code" / "agents"
    if not agents_dir.is_dir():
        return

    for src in sorted(agents_dir.glob("*.md")):
        raw = _read_text(src)
        _, base_frontmatter = parse_frontmatter(raw)
        variants = (
            _expand_agent_variants(src)
            if "generate_variants" in base_frontmatter
            else [(src.name, raw)]
        )
        for name, content in variants:
            _, frontmatter, valid = _resolve_content_frontmatter(content)
            yield Artifact(
                AGENT_DESCRIPTION_CHARS,
                target,
                name,
                len(frontmatter.get("description", "")) if valid else 0,
                src,
                allowances.get(AGENT_DESCRIPTION_CHARS, {}).get(name),
            )
            yield from _common_artifacts(content, target, name, src)


def iter_artifacts(
    roots: Iterable[Path], targets: tuple[str, ...] = CHECKED_TARGETS
) -> Iterator[Artifact]:
    """Measure every checked artifact under `roots` for `targets`.

    Args:
        roots: Prompts directories to scan - forward from owned source dirs,
            never derived from an installed destination. Passing a single
            overlay's own prompts directory scopes the scan to just its files.
        targets: Render targets to check.

    Yields:
        One `Artifact` per (metric, target, destination) measurement.
    """
    for root in roots:
        allowances, _ = _declared_allowances(root)
        for target in targets:
            yield from _iter_rendered_kind_artifacts(
                root, target, "rules", RULE_BYTES, RULE_LINES, allowances
            )
            yield from _iter_rendered_kind_artifacts(
                root, target, "workflows", WORKFLOW_BYTES, WORKFLOW_LINES, allowances
            )
            yield from _iter_skill_artifacts(root, target, allowances)
            yield from _iter_agent_artifacts(root, target, allowances)


def evaluate(artifacts: Iterable[Artifact]) -> list[Violation]:
    """Check measured artifacts against finals, schedules and allowances.

    A numeric artifact's ceiling is its metric's final, tightened further by
    its metric's active schedule step if that step gates this name, then
    replaced outright by a declared allowance if one applies. A bool artifact
    must simply be True.

    Args:
        artifacts: Measured artifacts, e.g. from `iter_artifacts`.

    Returns:
        Violations for every artifact that exceeded its ceiling.
    """
    violations: list[Violation] = []
    for artifact in artifacts:
        if artifact.metric not in FINALS:
            if artifact.value is not True:
                violations.append(
                    Violation(
                        artifact.metric,
                        artifact.target,
                        artifact.dest_name,
                        artifact.value,
                        True,
                        artifact.source,
                    )
                )
            continue

        ceiling = FINALS[artifact.metric]

        schedule = SCHEDULES.get(artifact.metric)
        active_threshold = (
            schedule.active_threshold_for(artifact.dest_name) if schedule else None
        )
        if active_threshold is not None:
            ceiling = min(ceiling, active_threshold)

        if artifact.allowance is not None:
            ceiling = artifact.allowance

        if artifact.value > ceiling:
            violations.append(
                Violation(
                    artifact.metric,
                    artifact.target,
                    artifact.dest_name,
                    artifact.value,
                    ceiling,
                    artifact.source,
                )
            )
    return violations


def parked_state_lines(artifacts: Iterable[Artifact]) -> list[str]:
    """Build one visibility line per metric with artifacts still over final.

    A guard that only speaks when it fails cannot report a parked schedule -
    this is the line both `install.main()`'s pre-flight and `llm-prompts
    check` print on every passing run, so the schedule's current position is
    always visible, not just its violations. A declared allowance covering an
    artifact takes it out of this report - it is not awaiting compression.

    Args:
        artifacts: Every measured artifact from a `check()` run.

    Returns:
        One formatted line per over-final metric, sorted by metric name.
    """
    over_final: dict[str, list[int]] = {}
    for artifact in artifacts:
        final = FINALS.get(artifact.metric)
        if (
            final is not None
            and isinstance(artifact.value, int)
            and artifact.value > final
            and artifact.allowance is None
        ):
            over_final.setdefault(artifact.metric, []).append(artifact.value)

    lines = []
    for metric in sorted(over_final):
        values = over_final[metric]
        final = FINALS[metric]
        unit = UNITS.get(metric, "")
        lines.append(
            f"{metric} current {max(values):,} final {final:,} {unit} - "
            f"{len(values)} files awaiting compression"
        )
    return lines


def stale_allowance_lines(
    roots: Iterable[Path], artifacts: Iterable[Artifact]
) -> list[str]:
    """Report declared allowances that matched no artifact under their own root.

    Args:
        roots: Prompts directories that were scanned.
        artifacts: Every measured artifact from a `check()` run.

    Returns:
        One non-fatal line per stale (root, metric, dest_name) declaration,
        naming the metric, the name, and the declaring file.
    """
    measured_by_root: dict[Path, set[tuple[str, str]]] = {}
    for artifact in artifacts:
        for root in roots:
            if artifact.source.is_relative_to(root):
                measured_by_root.setdefault(root, set()).add(
                    (artifact.metric, artifact.dest_name)
                )
                break

    lines = []
    for root in roots:
        allowances, _ = _declared_allowances(root)
        measured = measured_by_root.get(root, set())
        path = root / ALLOWANCES_FILENAME
        for metric in sorted(allowances):
            for dest_name in sorted(allowances[metric]):
                if (metric, dest_name) not in measured:
                    lines.append(
                        f"{path}: allowance for '{metric}.{dest_name}' matches no "
                        "measured artifact - remove it."
                    )
    return lines


def format_report(violations: list[Violation], errors: list[str] | None = None) -> str:
    """Format violations and declaration errors into a human-readable report.

    Args:
        violations: Violations from `evaluate`.
        errors: Declaration errors from `_declared_allowances`, if any.

    Returns:
        Declaration errors first under their own header, then a report line
        per violation naming the file, metric, actual value, threshold, and
        the compress-not-split remedy; a pass message if both are empty.
    """
    errors = errors or []
    if not violations and not errors:
        return "All prompt-size checks passed."
    lines = []
    if errors:
        lines.append("Prompt-size allowance declarations invalid:")
        lines.extend(f"  {e}" for e in errors)
    if violations:
        lines.append("Prompt-size guard failed:")
        for v in violations:
            unit = UNITS.get(v.metric, "")
            lines.append(
                f"  [{v.metric}] {v.dest_name} ({v.target}): actual {v.actual} > "
                f"threshold {v.threshold} {unit} ({v.source}) - compress, don't split."
            )
    return "\n".join(lines)


def check(
    roots: Iterable[Path],
    targets: tuple[str, ...] = CHECKED_TARGETS,
) -> CheckResult:
    """Measure every checked artifact under `roots` and evaluate it.

    Args:
        roots: Prompts directories to scan.
        targets: Render targets to check.

    Returns:
        The full check outcome: pass/fail, every measured artifact, any
        violations, declaration errors, stale allowances, and a report.
    """
    roots = list(roots)
    declaration_errors = []
    for root in roots:
        _, errors = _declared_allowances(root)
        declaration_errors.extend(errors)
    artifacts = list(iter_artifacts(roots, targets))
    violations = evaluate(artifacts)
    stale = stale_allowance_lines(roots, artifacts)
    return CheckResult(
        passed=not violations and not declaration_errors,
        artifacts=artifacts,
        violations=violations,
        report=format_report(violations, declaration_errors),
        declaration_errors=declaration_errors,
        stale=stale,
    )
