---
requires_env: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
---

# Agent teams: coordinate through the team

- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` gates `SendMessage`/the task list; installer-checked - MUST NOT re-verify via shell. Model tiers: `delegation.md`.
- A named team SHOULD default, even unasked, for sustained work (design, edits, verification, executing a plan). One-off work goes to an unnamed subagent - name one only with a stated follow-up, or it's waste.
- Effort is the latency lever, separate from model tier - a mechanical teammate pins low/medium via `subagent_type`.
- Teammate-side duties (claiming, reporting, handoff, rotation) live in the agent definitions, not here.

## Team patterns

- **Survey -> sub-lead -> parallel -> gated verify**: research+design+edits+check - `surveyor`s per thread (read-only), one Opus sub-lead to design/coordinate, sending main a roster spec + one final report; implementers report to it; `addBlockedBy` gates verification.
- **Multiple sub-leads**: independent tasks each get an Opus sub-lead + subteam, split by task not role, prefixed entries so workers don't cross-claim; don't coordinate by default - skip for one task, many facets.
- **Verify via `TaskList`, not idle pings**: pings carry no state info. After 3-4 with no change, one silent `TaskList` call - progress: say nothing; stuck: ask for the concrete action taken.
- **Resume an external plan directly**: picking up a plan approved elsewhere - main IS the sub-lead, no design step. Rebuild its dependency table as the TaskList graph; chain agents own a sequential slice, self-claiming their next stage once unblocked. Spawn only unblocked tasks; stop a one-shot agent on completion, leave a chain agent idle between stages to resume with context - route a follow-up the same way, never fresh.
- **Gate failure -> diagnose -> fix -> reverify**: a read-only Opus reasoner gets every failing test (not a summary), roots-causes from CURRENT code, reports the exact fix per file/line - resume if truncated. Route each fix to its file-owner (resume by name); re-run, repeat on new failure. After a migration list, grep independently for the old pattern - a snapshot, not exhaustive.

## Keep the main thread orchestration-only

- Loading this rule means teams are enabled - delegate from the FIRST unit, not inline until a team exists.
- Main spins up the team, assigns via the task list, checks results - use only `Agent`/`SendMessage`/`Task*` and light verification; catching itself reading, writing or investigating: stop and delegate. Never re-run a mechanical command (status/find/build) to double-check.
- MUST NOT arbitrate between teammates - route to a named Opus delegate. A quick lookup or small edit also goes to a subagent - urgency isn't an exemption.
- No exception for a judgment-bearing skill (e.g. `refine-plan`) - spawn a teammate even via slash command.

## Teammate communication

- Surface a teammate message only when substantive: a result, question, or blocker; MUST NOT relay `idle_notification` pings - stay silent, or a single emoji. `idleReason: "available"` means it sends nothing unsolicited - `SendMessage` for status.
- Named teammates SHOULD `SendMessage` directly - an Opus designer hands straight to Sonnet workers; main MUST NOT relay between reachable teammates. Cross-agent messages MUST be short, one line where possible; the SPAWN prompt carries the full contract - never re-brief later.

## Coordinate via the shared task list

- Default to `TaskCreate` once a second independent piece exists, not once full scope is known; main creates/refines tasks, MUST NOT claim or execute them.
- Spawn teammates for expected roles before the list is full, so the team self-claims as tasks land.
- Size each task for one member, splitting oversized contracts first; `addBlockedBy`/`addBlocks` self-sequences the team unpolled.
- Own Opus-tier tasks (design, root-cause, judgment) at creation; leave mechanical ones unowned except a single-seat resource.
- A fully-specified plan (gate-passed design, handoff doc, TDD sequence) MUST go on the task list; grow the team where the backlog exceeds the roster, or new work fits no role.
- A roster spec MUST carry each task's subject and ID, checked against `TaskList` before spawning; only the lead spawns a named teammate - a member needing more hands sends the lead a roster spec.

## Stopping and persistence - `TaskList` dies with the session

- `TaskStop` a teammate once its task is done with nothing queued - not later, unless same-role work is imminent.
- A finished teammate left alive can self-claim under an unassigned owner - check it's who you spawned.
- MUST NOT stop a producer that reported on its idle ping alone - wait for the consumer to confirm input.
- Spawn a fresh replacement for a member reporting high context - don't run it degraded.
- A correctly stopped teammate can still leave unclaimed items. Ending a lead session, run `TaskList` and give every open item a home: a memory `task/` entity, plus `handoff`/`session-end` if work remains.
