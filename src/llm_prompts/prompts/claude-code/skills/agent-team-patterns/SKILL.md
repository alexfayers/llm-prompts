---
name: agent-team-patterns
description: Team patterns for research, design, parallel edits and verification work: the survey/sub-lead pipeline, multiple sub-leads, and verifying sub-lead progress. Load when standing up a team.
requires_env: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
---

# Agent team patterns

Load when standing up a team. `agent-teams.md` carries the orchestration rules; this file carries the patterns.

## Pattern: survey -> sub-lead design -> parallel execution -> gated verification

- SHOULD use this for a change needing research, then design, then several independent edits, then a checking pass.
- Main SHOULD spawn one `surveyor` per research thread first, concurrently - read-only by tool grant, safer than telling a `reasoner`/`worker` to stay read-only. Each spawn prompt SHOULD name its consumer, which defaults to `main`.
- Main SHOULD then spawn exactly one named Opus sub-lead pointed at the surveyors, and SHOULD leave design, task-writing and implementer coordination to it.
- The sub-lead SHOULD hand main a ready-to-spawn roster spec instead of spawning, and SHOULD send main exactly one final report.
- Implementers SHOULD work in parallel and report to the sub-lead. SHOULD gate the verification task with `addBlockedBy` on every implementation task so it self-starts.
- Main's whole footprint: spawn surveyors, spawn the sub-lead, spawn the roster it asks for, read its one final report.

## Multiple sub-leads for multiple independent tasks

- For several genuinely independent tasks, SHOULD spawn one named Opus sub-lead each, running its own subteam and reporting to main independently. SHOULD split by task, not by role.
- MUST prefix each subteam's task entries so workers do not cross-claim.
- Sub-leads SHOULD NOT coordinate with each other by default; MAY use cross-sub-lead `SendMessage` if a real shared dependency emerges.
- SHOULD NOT use this for one task with multiple facets - that is still the single-sub-lead pattern.

## Verify sub-lead coordination against TaskList, not idle pings

- Idle pings carry no task-state information; silence is not evidence of progress.
- After 3-4 consecutive idle pings with no task changing state, MUST make an unprompted, silent `TaskList` call.
- If it shows real progress, MUST say nothing. If tasks are stuck `pending`/unowned despite a claimed unblock, MUST ask the sub-lead for the concrete action taken, not a status word.
