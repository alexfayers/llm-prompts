"""Measures the total bytes an install writes per target, for `collection_bytes`.

Unlike the per-file metrics in `size_guard`, a collection total must count each
installed artifact exactly once, so every kind is resolved with the same
overlay priority `install.main` applies rather than measuring each root
independently. It also counts what no per-file metric does: a skill's whole
`SKILL.md` as materialized, and every generated claude-code agent variant.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from .install import (
    _builtin_skill_vars,
    _collect_content_srcs,
    _excluded_targets,
    _expand_agent_variants,
    _linked_content,
    _passes_requires_gate,
    _read_text,
    _rendered_content,
    _resolve_priority_sources,
)
from .render_template import parse_frontmatter, substitute_variables
from .size_guard import (
    CHECKED_TARGETS,
    Artifact,
    Violation,
    _agent_for,
    _declared_allowances,
    _own_vars_path,
)
from .size_limits import COLLECTION_BYTES, COLLECTION_SCHEDULE


def _rendered_kind_bytes(
    root: Path, overlays: Sequence[Path], target: str, subdir: str
) -> int:
    """Sum installed bytes for one rules/workflows subdir, priority resolved.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        target: Render target.
        subdir: Content subdirectory (``"rules"`` or ``"workflows"``).

    Returns:
        Total bytes the install writes for this target and subdirectory.
    """
    agent = _agent_for(target, root)
    vars_path = _own_vars_path(target)
    total = 0
    for _, src, agent_specific in _collect_content_srcs(
        agent,
        subdir,
        root / "shared" / subdir,
        [d / "shared" / subdir for d in overlays],
        [d / target / subdir for d in overlays],
    ):
        content = (
            _linked_content(src)
            if agent_specific
            else _rendered_content(src, vars_path, target)
        )
        total += len(content.encode())
    return total


def _skill_bytes(root: Path, overlays: Sequence[Path], target: str) -> int:
    """Sum installed ``SKILL.md`` bytes for one target, priority resolved.

    Measures the whole substituted file `_materialize_builtin_skill` writes,
    not just the body `skill_body_bytes` gates. A skill's sibling files are
    symlinked rather than copied, so they add no installed bytes.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        target: Render target.

    Returns:
        Total ``SKILL.md`` bytes the install writes for this target.
    """
    variables = _builtin_skill_vars(_own_vars_path(target))

    def gate(skill_dir: Path) -> bool:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            return False
        if not _passes_requires_gate(skill_md):
            return False
        return target not in _excluded_targets(skill_md)

    resolved = _resolve_priority_sources(
        [
            *(d / "shared" / "skills" for d in overlays),
            root / "shared" / "skills",
            root / target / "skills",
            *(d / target / "skills" for d in overlays),
        ],
        lambda d: [p for p in sorted(d.iterdir()) if p.is_dir()],
        lambda p: p.name,
        gate,
    )
    return sum(
        len(substitute_variables(_read_text(d / "SKILL.md"), variables).encode())
        for _, d in resolved
    )


def _agent_bytes(root: Path, overlays: Sequence[Path], target: str) -> int:
    """Sum installed agent-definition bytes, expanding generated variants.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        target: Render target - agents are claude-code only.

    Returns:
        Total agent-definition bytes installed, or 0 for any other target.
    """
    if target != "claude-code":
        return 0
    total = 0
    for _, src in _resolve_priority_sources(
        [
            *(d / "claude-code" / "agents" for d in overlays),
            root / "claude-code" / "agents",
        ],
        lambda d: sorted(d.glob("*.md")),
        lambda p: p.name,
    ):
        raw = _read_text(src)
        _, frontmatter = parse_frontmatter(raw)
        variants = (
            _expand_agent_variants(src)
            if "generate_variants" in frontmatter
            else [(src.name, raw)]
        )
        total += sum(len(content.encode()) for _, content in variants)
    return total


def collection_artifacts(
    roots: Sequence[Path], targets: tuple[str, ...] = CHECKED_TARGETS
) -> list[Artifact]:
    """Measure one per-target collection total across every root.

    Args:
        roots: Prompts directories, this package's own first and discovered
            overlays after it - the shape both `install.main` and the `check`
            subcommand already assemble.
        targets: Render targets to measure.

    Returns:
        One `Artifact` per target, carrying that target's total installed bytes
        and any `collection_bytes` allowance the base root declares for it.
    """
    if not roots:
        return []
    root, overlays = roots[0], roots[1:]
    allowances, _ = _declared_allowances(root)
    declared = allowances.get(COLLECTION_BYTES, {})
    return [
        Artifact(
            COLLECTION_BYTES,
            target,
            target,
            _rendered_kind_bytes(root, overlays, target, "rules")
            + _rendered_kind_bytes(root, overlays, target, "workflows")
            + _skill_bytes(root, overlays, target)
            + _agent_bytes(root, overlays, target),
            root,
            declared.get(target),
        )
        for target in targets
    ]


def evaluate_collection(artifacts: Iterable[Artifact]) -> list[Violation]:
    """Check per-target collection totals against the active schedule step.

    `collection_bytes` has no final to fall back on the way the per-file
    metrics do, so the active step is the whole ceiling rather than a
    tightening on top of one - which is why these artifacts are evaluated here
    rather than by `size_guard.evaluate`.

    Args:
        artifacts: Collection artifacts from `collection_artifacts`.

    Returns:
        Violations for every target over its ceiling.

    Raises:
        KeyError: If `COLLECTION_SCHEDULE.active_step` names no known step.
    """
    active = COLLECTION_SCHEDULE.active_threshold()
    violations: list[Violation] = []
    for artifact in artifacts:
        ceiling = active if artifact.allowance is None else artifact.allowance
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
