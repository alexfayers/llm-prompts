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

from jinja2 import TemplateError

from .install import (
    _GATING_FRONTMATTER_KEYS,
    _agent_source_dirs,
    _append_included_rules,
    _builtin_skill_vars,
    _collect_content_srcs,
    _expand_agent_variants,
    _linked_content,
    _passes_requires_gate,
    _PiRuleBundle,
    _rendered_content,
    _resolve_priority_sources,
    _RuleSources,
    _targets_agent,
    content_subdirs,
)
from .render_template import (
    _read_text,
    parse_frontmatter,
    strip_gating_keys,
    substitute_variables,
)
from .size_guard import (
    CHECKED_TARGETS,
    Artifact,
    Violation,
    _agent_for,
    _declared_allowances,
    _own_vars_path,
    ceiling_for,
)
from .size_limits import COLLECTION_BYTES


def _rendered_kind_bytes(
    root: Path,
    overlays: Sequence[Path],
    target: str,
    subdir: str,
    vars_root: Path | None = None,
) -> int:
    """Sum installed bytes for one rules/workflows subdir, priority resolved.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        target: Render target.
        subdir: Content subdirectory (``"rules"`` or ``"workflows"``).
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

    Returns:
        Total bytes the install writes for this target and subdirectory.
    """
    agent = _agent_for(target, root)
    vars_path = _own_vars_path(target, vars_root)
    total = 0
    for _, src, agent_specific in _collect_content_srcs(
        agent,
        subdir,
        root / "shared" / subdir,
        [d / "shared" / subdir for d in overlays],
        [d / target / subdir for d in overlays],
    ):
        try:
            content = (
                _linked_content(src)
                if agent_specific
                else _rendered_content(src, vars_path, target)
            )
        except TemplateError:
            continue
        total += len(content.encode())
    return total


def _skill_bytes(
    root: Path,
    overlays: Sequence[Path],
    target: str,
    vars_root: Path | None = None,
) -> int:
    """Sum installed ``SKILL.md`` bytes for one target, priority resolved.

    Measures the whole substituted file `_materialize_builtin_skill` writes,
    not just the body `skill_body_bytes` gates. A skill's sibling files are
    symlinked rather than copied, so they add no installed bytes.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        target: Render target.
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

    Returns:
        Total ``SKILL.md`` bytes the install writes for this target.
    """
    variables = _builtin_skill_vars(_own_vars_path(target, vars_root))

    def gate(skill_dir: Path) -> bool:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            return False
        if not _passes_requires_gate(skill_md, target):
            return False
        return _targets_agent(skill_md, target)

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
    total = 0
    for _, skill_dir in resolved:
        try:
            substituted = strip_gating_keys(
                substitute_variables(_read_text(skill_dir / "SKILL.md"), variables),
                _GATING_FRONTMATTER_KEYS,
            )
        except TemplateError:
            continue
        total += len(substituted.encode())
    return total


def _agent_bytes(
    root: Path,
    overlays: Sequence[Path],
    target: str,
    vars_root: Path | None = None,
) -> int:
    """Sum installed agent-definition bytes, expanding variants and included rules.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        target: Render target - agents are claude-code only.
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

    Returns:
        Total agent-definition bytes installed, or 0 for any other target.
    """
    if target != "claude-code":
        return 0
    variables = _builtin_skill_vars(_own_vars_path(target, vars_root))
    rules = _RuleSources.collect(_agent_for(target, root), overlays)
    total = 0
    for _, src in _resolve_priority_sources(
        _agent_source_dirs(root, overlays, target),
        lambda d: sorted(d.glob("*.md")),
        lambda p: p.name,
    ):
        try:
            rendered = substitute_variables(_read_text(src), variables)
        except TemplateError:
            continue
        _, frontmatter = parse_frontmatter(rendered)
        files = (
            _expand_agent_variants(src, variables=variables)
            if "generate_variants" in frontmatter
            else [(src.name, strip_gating_keys(rendered, _GATING_FRONTMATTER_KEYS))]
        )
        total += sum(
            len(_append_included_rules(content, src, rules).encode())
            for _, content in files
        )
    return total


def _pi_bundle_bytes(
    root: Path, overlays: Sequence[Path], vars_root: Path | None = None
) -> int:
    """Sum the bytes of the global ``AGENTS.md`` and the rule files outside it.

    A rule in ``AGENTS.md`` is not counted again as a rule file. Agent
    definitions are not counted: `pi_role_prompt_bytes` guards each expanded
    role prompt.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

    Returns:
        Total bytes of ``AGENTS.md`` and the rule files outside it.
    """
    bundle = _PiRuleBundle.build(
        _agent_for("pi", root), overlays, vars_path=_own_vars_path("pi", vars_root)
    )
    in_agents_md = set(bundle.lead_names())
    return len(bundle.lead_text().encode()) + sum(
        len(text.encode())
        for name, text in bundle.texts.items()
        if name not in in_agents_md
    )


def collection_artifacts(
    roots: Sequence[Path],
    targets: tuple[str, ...] = CHECKED_TARGETS,
    vars_root: Path | None = None,
) -> list[Artifact]:
    """Measure one per-target collection total across every root.

    Args:
        roots: Prompts directories, this package's own first and discovered
            overlays after it - the shape both `install.main` and the `check`
            subcommand already assemble.
        targets: Render targets to measure.
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

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
            sum(
                _rendered_kind_bytes(root, overlays, target, subdir, vars_root)
                for subdir in content_subdirs(target)
                if not (target == "pi" and subdir == "rules")
            )
            + (_pi_bundle_bytes(root, overlays, vars_root) if target == "pi" else 0)
            + _skill_bytes(root, overlays, target, vars_root)
            + _agent_bytes(root, overlays, target, vars_root),
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
    violations: list[Violation] = []
    for artifact in artifacts:
        ceiling = ceiling_for(artifact)
        assert ceiling is not None
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
