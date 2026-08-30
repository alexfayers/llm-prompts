"""Single source of truth for the prompt-size guard's thresholds and schedules.

Every threshold here is either a fixed design target (the ``final`` an artifact
must eventually satisfy, or a schedule step's ceiling) or batch membership
derived from measuring real rendered/substituted content against those
thresholds - never a hand-copied estimate. ``size_guard`` and its tests, plus
this module's own tests, read every number from here; no metric literal should
be repeated in a message, a test, or a second code path.
"""

from __future__ import annotations

from dataclasses import dataclass

# Metric identifiers, matching the "M<n>" table in the size-guard design.
RULE_LINES = "rule_lines"
RULE_BYTES = "rule_bytes"
SKILL_BODY_BYTES = "skill_body_bytes"
WORKFLOW_BYTES = "workflow_bytes"
WORKFLOW_LINES = "workflow_lines"
SKILL_DESCRIPTION_CHARS = "skill_description_chars"
AGENT_DESCRIPTION_CHARS = "agent_description_chars"
COLLECTION_BYTES = "collection_bytes"
FRONTMATTER_VALID = "frontmatter_valid"
NO_UNSUBSTITUTED_PLACEHOLDERS = "no_unsubstituted_placeholders"

UNITS: dict[str, str] = {
    RULE_LINES: "rendered lines",
    RULE_BYTES: "rendered bytes",
    SKILL_BODY_BYTES: "substituted body bytes",
    WORKFLOW_BYTES: "rendered bytes",
    WORKFLOW_LINES: "rendered lines",
    SKILL_DESCRIPTION_CHARS: "chars",
    AGENT_DESCRIPTION_CHARS: "chars, post-expansion",
    COLLECTION_BYTES: "owned bytes per target",
}

FINALS: dict[str, int] = {
    RULE_LINES: 200,
    RULE_BYTES: 5_000,
    SKILL_BODY_BYTES: 5_000,
    WORKFLOW_BYTES: 5_000,
    WORKFLOW_LINES: 200,
    SKILL_DESCRIPTION_CHARS: 200,
    AGENT_DESCRIPTION_CHARS: 200,
    COLLECTION_BYTES: 50_000,
}

# `_apply_variant_frontmatter` appends " [<model>, <effort> effort]" to every
# generated agent's description; the longest real model/effort combination
# (sonnet + medium) sets how much of the final a base template may itself use.
_LONGEST_VARIANT_SUFFIX = " [sonnet, medium effort]"
AGENT_BASE_DESCRIPTION_MAX_CHARS = FINALS[AGENT_DESCRIPTION_CHARS] - len(
    _LONGEST_VARIANT_SUFFIX
)


@dataclass(frozen=True)
class ScheduleStep:
    """One step of a metric's per-file descent schedule.

    Args:
        name: Step identifier (e.g. ``"W2"``, ``"S1"``, ``"D1"``).
        threshold: Ceiling enforced on every name in ``files`` while this step
            is the schedule's active step.
        files: Destination filenames/skill names this step gates. A name can
            appear in more than one step - some artifacts need several
            successive cuts to reach the metric's final threshold.
    """

    name: str
    threshold: int
    files: frozenset[str]


@dataclass(frozen=True)
class Schedule:
    """An ordered per-file descent schedule for one metric.

    Args:
        steps: Steps in the order they are meant to be worked through.
        active_step: Name of the step currently enforced, or ``None`` before
            the schedule is engaged. A name the schedule would otherwise gate
            falls back to the metric's final until its step becomes active.
    """

    steps: tuple[ScheduleStep, ...]
    active_step: str | None = None

    def active_threshold_for(self, name: str) -> int | None:
        """Return the active step's threshold if it gates ``name``.

        Args:
            name: Destination filename or skill name to check.

        Returns:
            The active step's threshold, or None if the schedule has not been
            engaged, or its active step does not gate this name.
        """
        if self.active_step is None:
            return None
        for step in self.steps:
            if step.name == self.active_step:
                return step.threshold if name in step.files else None
        return None


@dataclass(frozen=True)
class CollectionStep:
    """One step of the per-target collection-bytes schedule (M8).

    Args:
        name: Step identifier (e.g. ``"open"``, ``"W1"``).
        threshold: Ceiling enforced on each checked target's owned collection
            size.
    """

    name: str
    threshold: int


@dataclass(frozen=True)
class CollectionSchedule:
    """Hand-set per-target collection-byte descent schedule.

    Unlike the per-file schedules, collection_bytes has no `final` to fall back
    on - `FINALS` records the terminal step's target, not a ceiling in force -
    so the active step is always the whole ceiling rather than an optional
    tightening on top of one. The total is computable from sources alone; its
    value depends on which roots are scanned, so this repo's own test suite
    measures a smaller collection than an install that discovers overlays.

    Args:
        steps: Steps in the order they are meant to be worked through.
        active_step: Name of the step currently enforced.
    """

    steps: tuple[CollectionStep, ...]
    active_step: str

    def active_threshold(self) -> int:
        """Return the currently active step's threshold.

        Returns:
            The active step's byte ceiling.

        Raises:
            KeyError: If ``active_step`` does not name a known step.
        """
        for step in self.steps:
            if step.name == self.active_step:
                return step.threshold
        raise KeyError(self.active_step)


# Per-file schedules. Membership was computed by rendering/substituting each
# artifact and comparing against the step's threshold; a name appears in every
# step whose threshold it currently exceeds, so artifacts needing several
# successive cuts (e.g. memory.md, coding.md) appear in more than one step.
# `active_step` stays None until a metric's gated files are compressed and
# verified; rule_lines and rule_bytes have their W2 step engaged, the rest do not.
SCHEDULES: dict[str, Schedule] = {
    RULE_LINES: Schedule(
        steps=(ScheduleStep("W2", 200, frozenset({"memory.md"})),),
        active_step="W2",
    ),
    RULE_BYTES: Schedule(
        steps=(
            ScheduleStep("W2", 13_000, frozenset({"agent-teams.md", "memory.md"})),
            ScheduleStep(
                "W3",
                9_500,
                frozenset(
                    {
                        "agent-teams.md",
                        "memory.md",
                        "planning.md",
                        "delegation.md",
                        "coding.md",
                    }
                ),
            ),
            ScheduleStep(
                "W4",
                5_000,
                frozenset(
                    {
                        "agent-teams.md",
                        "memory.md",
                        "planning.md",
                        "delegation.md",
                        "coding.md",
                    }
                ),
            ),
        ),
        active_step="W4",
    ),
    SKILL_BODY_BYTES: Schedule(
        steps=(
            ScheduleStep("S1", 15_000, frozenset({"oncall", "cr"})),
            ScheduleStep("S2", 8_000, frozenset({"oncall", "cr", "tidy-code"})),
            ScheduleStep(
                "S3",
                6_000,
                frozenset({"oncall", "cr", "tidy-code", "git-usage", "session-start"}),
            ),
            ScheduleStep(
                "S4",
                5_000,
                frozenset(
                    {
                        "oncall",
                        "cr",
                        "tidy-code",
                        "git-usage",
                        "session-start",
                        "git-tidy",
                        "handoff",
                        "session-end",
                    }
                ),
            ),
        ),
    ),
    SKILL_DESCRIPTION_CHARS: Schedule(
        steps=(
            ScheduleStep("D1", 260, frozenset({"handoff", "ask-codex"})),
            ScheduleStep(
                "D2",
                230,
                frozenset({"handoff", "ask-codex", "git-tidy", "pickup", "grill-me"}),
            ),
            ScheduleStep(
                "D3",
                205,
                frozenset(
                    {
                        "handoff",
                        "ask-codex",
                        "git-tidy",
                        "pickup",
                        "grill-me",
                        "todos",
                        "tidy-code",
                        "tdd",
                    }
                ),
            ),
            ScheduleStep(
                "D4",
                200,
                frozenset(
                    {
                        "handoff",
                        "ask-codex",
                        "git-tidy",
                        "pickup",
                        "grill-me",
                        "todos",
                        "tidy-code",
                        "tdd",
                    }
                ),
            ),
        ),
    ),
    AGENT_DESCRIPTION_CHARS: Schedule(
        steps=(
            ScheduleStep(
                "D1",
                350,
                frozenset(
                    {
                        "architect-opus-medium.md",
                        "architect-opus-high.md",
                        "architect-opus-xhigh.md",
                    }
                ),
            ),
            ScheduleStep(
                "D2",
                200,
                frozenset(
                    {
                        "architect-opus-medium.md",
                        "architect-opus-high.md",
                        "architect-opus-xhigh.md",
                        "surveyor-sonnet-medium.md",
                        "surveyor-sonnet-high.md",
                        "surveyor-sonnet-low.md",
                    }
                ),
            ),
        ),
    ),
}

COLLECTION_SCHEDULE = CollectionSchedule(
    steps=(
        CollectionStep("open", 425_000),
        CollectionStep("W1", 135_000),
        CollectionStep("W2", 95_000),
        CollectionStep("W3", 75_000),
        CollectionStep("W4", 50_000),
    ),
    active_step="open",
)

# Transitional aliases for the pre-rename CORPUS_* names, kept only while a
# concurrent change holds `tests/test_prompt_sizes.py`. Remove both these and
# that module's imports once it lands.
CORPUS_BYTES = COLLECTION_BYTES
CorpusStep = CollectionStep
CorpusSchedule = CollectionSchedule
CORPUS_SCHEDULE = COLLECTION_SCHEDULE
