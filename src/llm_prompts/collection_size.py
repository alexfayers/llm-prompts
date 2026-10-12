"""Measures the bytes one session can load per target, for `collection_bytes`.

Unlike the per-file metrics in `size_guard`, a collection total must count each
installed artifact exactly once, so every kind is resolved with the same
overlay priority `install.main` applies rather than measuring each root
independently. It also counts what no per-file metric does: a skill's whole
`SKILL.md` as materialized. Agent bodies are measured but not totalled.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
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
    _pi_agent_dialect,
    _pi_definitions,
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
    split_frontmatter,
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
from .size_limits import (
    ALWAYS_AGENT_FRONTMATTER_BYTES,
    ALWAYS_LOADED_METRICS,
    ALWAYS_RULE_BYTES,
    ALWAYS_SKILL_FRONTMATTER_BYTES,
    COLLECTION_BYTES,
    ON_DEMAND_AGENT_BODY_BYTES,
    ON_DEMAND_ROLE_RULE_BYTES,
    ON_DEMAND_SKILL_BODY_BYTES,
    ON_DEMAND_WORKFLOW_BYTES,
    START_BYTES,
    WORST_CASE_ON_DEMAND_METRICS,
)

_KIND_METRICS = {
    "rules": ALWAYS_RULE_BYTES,
    "workflows": ON_DEMAND_WORKFLOW_BYTES,
}


@dataclass(frozen=True)
class LoadedBytes:
    """Installed bytes split by when a session loads them.

    Args:
        frontmatter: Bytes of the frontmatter block, which a session lists up
            front.
        body: Bytes after the frontmatter, loaded when the artifact is used.
    """

    frontmatter: int = 0
    body: int = 0

    @property
    def total(self) -> int:
        """Frontmatter plus body bytes."""
        return self.frontmatter + self.body

    def __add__(self, other: LoadedBytes) -> LoadedBytes:
        return LoadedBytes(self.frontmatter + other.frontmatter, self.body + other.body)

    @classmethod
    def of(cls, content: str) -> LoadedBytes:
        """Split installed content at the end of its frontmatter block.

        Args:
            content: Installed file content.

        Returns:
            The content's frontmatter and body byte counts.
        """
        split = split_frontmatter(content)
        body = split[1] if split else content
        return cls(len(content.encode()) - len(body.encode()), len(body.encode()))


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
) -> LoadedBytes:
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
        ``SKILL.md`` bytes the install writes for this target, split into
        frontmatter and body.
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
    total = LoadedBytes()
    for _, skill_dir in resolved:
        try:
            substituted = strip_gating_keys(
                substitute_variables(_read_text(skill_dir / "SKILL.md"), variables),
                _GATING_FRONTMATTER_KEYS,
            )
        except TemplateError:
            continue
        total += LoadedBytes.of(substituted)
    return total


def _agent_bytes(
    root: Path,
    overlays: Sequence[Path],
    target: str,
    vars_root: Path | None = None,
) -> LoadedBytes:
    """Sum installed agent-definition bytes, expanding variants and included rules.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        target: Render target - agents are claude-code only.
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

    Returns:
        Agent-definition bytes installed, split into frontmatter and body, or
        zero for any other target.
    """
    if target != "claude-code":
        return LoadedBytes()
    variables = _builtin_skill_vars(_own_vars_path(target, vars_root))
    rules = _RuleSources.collect(_agent_for(target, root), overlays)
    total = LoadedBytes()
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
        for _, content in files:
            total += LoadedBytes.of(_append_included_rules(content, src, rules))
    return total


def _pi_bundle_bytes(
    root: Path, overlays: Sequence[Path], vars_root: Path | None = None
) -> LoadedBytes:
    """Sum the bytes of the global ``AGENTS.md`` and the rule files outside it.

    A rule in ``AGENTS.md`` is not counted again as a rule file. The global
    ``AGENTS.md`` loads in every session, so it is the ``frontmatter`` part. The
    other rules load when a role that selects them is spawned, so they are the
    ``body`` part.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

    Returns:
        Bytes of ``AGENTS.md`` as ``frontmatter`` and of the other rule files as
        ``body``.
    """
    bundle = _PiRuleBundle.build(
        _agent_for("pi", root), overlays, vars_path=_own_vars_path("pi", vars_root)
    )
    in_agents_md = set(bundle.lead_names())
    return LoadedBytes(
        len(bundle.lead_text().encode()),
        sum(
            len(text.encode())
            for name, text in bundle.texts.items()
            if name not in in_agents_md
        ),
    )


def _pi_definition_bytes(
    root: Path, overlays: Sequence[Path], vars_root: Path | None = None
) -> LoadedBytes:
    """Sum the pi agent definition files, which reference rules rather than inline them.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

    Returns:
        Bytes of the installed definitions, split into frontmatter and body.
    """
    vars_path = _own_vars_path("pi", vars_root)
    bundle = _PiRuleBundle.build(_agent_for("pi", root), overlays, vars_path=vars_path)
    definitions, _ = _pi_definitions(
        _agent_source_dirs(root, overlays, "pi"),
        bundle,
        _pi_agent_dialect(root, overlays, strict_skills=False),
        _builtin_skill_vars(vars_path),
    )
    total = LoadedBytes()
    for _, _, content in definitions:
        total += LoadedBytes.of(content)
    return total


def _target_parts(
    root: Path, overlays: Sequence[Path], target: str, vars_root: Path | None
) -> dict[str, int]:
    """Measure one target's installed bytes by when a session loads them.

    Args:
        root: This package's own prompts directory.
        overlays: Discovered overlay prompts directories, in priority order.
        target: Render target.
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

    Returns:
        Installed bytes by part metric.
    """
    parts = dict.fromkeys(
        (
            ALWAYS_RULE_BYTES,
            ALWAYS_SKILL_FRONTMATTER_BYTES,
            ALWAYS_AGENT_FRONTMATTER_BYTES,
            ON_DEMAND_ROLE_RULE_BYTES,
            ON_DEMAND_SKILL_BODY_BYTES,
            ON_DEMAND_AGENT_BODY_BYTES,
            ON_DEMAND_WORKFLOW_BYTES,
        ),
        0,
    )
    for subdir in content_subdirs(target):
        if target == "pi" and subdir == "rules":
            bundle = _pi_bundle_bytes(root, overlays, vars_root)
            parts[ALWAYS_RULE_BYTES] += bundle.frontmatter
            parts[ON_DEMAND_ROLE_RULE_BYTES] += bundle.body
        else:
            parts[_KIND_METRICS[subdir]] += _rendered_kind_bytes(
                root, overlays, target, subdir, vars_root
            )
    skills = _skill_bytes(root, overlays, target, vars_root)
    parts[ALWAYS_SKILL_FRONTMATTER_BYTES] = skills.frontmatter
    parts[ON_DEMAND_SKILL_BODY_BYTES] = skills.body
    agents = (
        _pi_definition_bytes(root, overlays, vars_root)
        if target == "pi"
        else _agent_bytes(root, overlays, target, vars_root)
    )
    parts[ALWAYS_AGENT_FRONTMATTER_BYTES] = agents.frontmatter
    parts[ON_DEMAND_AGENT_BODY_BYTES] = agents.body
    return parts


def collection_artifacts(
    roots: Sequence[Path],
    targets: tuple[str, ...] = CHECKED_TARGETS,
    vars_root: Path | None = None,
) -> list[Artifact]:
    """Measure one per-target collection total, and its parts, across every root.

    The total is the worst case for one session: the bytes loaded at session
    start plus every skill body and workflow. Agent bodies and pi role-only
    rules are parts but not in the total, as each loads only into its own
    spawned agent's session. `pi_role_prompt_bytes` guards those prompts.

    Args:
        roots: Prompts directories, this package's own first and discovered
            overlays after it - the shape both `install.main` and the `check`
            subcommand already assemble.
        targets: Render targets to measure.
        vars_root: Prompts directory to read variables from, instead of this
            package's own.

    Returns:
        One `collection_bytes` `Artifact` per target, carrying that target's
        worst-case session bytes and any allowance the base root declares for
        it, then report-only artifacts per target: `start_bytes` and one for
        each part that splits the bytes into up-front and on-demand.
    """
    if not roots:
        return []
    root, overlays = roots[0], roots[1:]
    allowances, _ = _declared_allowances(root)
    declared = allowances.get(COLLECTION_BYTES, {})
    measured = {t: _target_parts(root, overlays, t, vars_root) for t in targets}
    start = {
        t: sum(parts[m] for m in ALWAYS_LOADED_METRICS) for t, parts in measured.items()
    }
    return [
        *(
            Artifact(
                COLLECTION_BYTES,
                target,
                target,
                start[target] + sum(parts[m] for m in WORST_CASE_ON_DEMAND_METRICS),
                root,
                declared.get(target),
            )
            for target, parts in measured.items()
        ),
        *(
            Artifact(START_BYTES, target, target, start[target], root)
            for target in measured
        ),
        *(
            Artifact(metric, target, target, value, root)
            for target, parts in measured.items()
            for metric, value in parts.items()
        ),
    ]


def evaluate_collection(artifacts: Iterable[Artifact]) -> list[Violation]:
    """Check per-target collection totals against the active schedule step.

    `collection_bytes` has no final to fall back on the way the per-file
    metrics do, so the active step is the whole ceiling rather than a
    tightening on top of one - which is why these artifacts are evaluated here
    rather than by `size_guard.evaluate`.

    Args:
        artifacts: Collection artifacts from `collection_artifacts`. Only the
            `collection_bytes` totals have a ceiling.

    Returns:
        Violations for every target over its ceiling.

    Raises:
        KeyError: If `COLLECTION_SCHEDULE.active_step` names no known step.
    """
    violations: list[Violation] = []
    for artifact in artifacts:
        if artifact.metric != COLLECTION_BYTES:
            continue
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
