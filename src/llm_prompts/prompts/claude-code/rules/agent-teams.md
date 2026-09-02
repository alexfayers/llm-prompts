---
requires_env: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
---

# Agent teams: coordinate through the team

- Requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` (gates direct `SendMessage` and the shared task list); already installer-checked, so MUST NOT re-verify via shell. Model tiers: `delegation.md`.
- A named team SHOULD default for sustained work (design, parallel edits, verification) not only on an explicit ask. One-off work (a command run, bounded lookup, single-turn question) SHOULD go to an unnamed subagent - MUST be able to state the follow-up message you expect before naming one; a name held for optionality is waste.
- Effort is the latency lever, separate from model tier - for a mechanical teammate, SHOULD pick a `subagent_type` pinning low/medium effort.
- Standing up a team MUST load `agent-team-patterns` first, for the survey/sub-lead pipeline, multiple sub-leads, and verifying sub-lead progress.
- Teammate-side duties - claiming, reporting, handing off, rotating out - live in the agent definition bodies, not here.

## Keep the main thread orchestration-only

- Main spins up the team, assigns work via the task list, checks results, and MUST use only `Agent`, `SendMessage`, the `Task*` tools and light verification - reading what a teammate produced. MUST NOT do delegable work itself - MUST stop and delegate on catching itself reading a file, writing code, or investigating - and MUST NOT re-run a mechanical command (`git status`/`find`/a build) to double-check.
- MUST NOT arbitrate between teammates - route the call to a named Opus delegate.
- MUST route a quick lookup (`find`/`grep`/`ls`/status) or a small edit the user wants fast to a subagent - urgency is not an exemption.
- No exception for a judgment-bearing skill (e.g. `refine-plan`), even via slash command: MUST spawn a teammate for it.

## Only surface substantive teammate updates

- MUST surface a teammate message only when substantive: a result, a question needing user input, or a blocker; MUST NOT relay `idle_notification` pings - stay silent, or a single emoji and nothing else.
- `idleReason: "available"` means the teammate stopped and sends nothing unsolicited - `SendMessage` it for status.

## Let the team talk to each other

- Named teammates SHOULD `SendMessage` each other directly - an Opus designer hands work straight to Sonnet workers; Main MUST NOT relay between two teammates that can reach each other.
- Cross-agent messages MUST be very short by default - one line where possible ("run the tests"). A named agent's SPAWN prompt carries the contract: who to message, how to ask, and every constraint that binds it. MUST NOT re-brief an agent in later messages.

## Coordinate through the shared task list

- Delegated work SHOULD default to `TaskCreate` once more than one independent piece exists, not once full scope is known.
- Main creates and refines tasks; it MUST NOT claim or execute them.
- SHOULD spawn teammates for expected roles before the list is full, so a standing team self-claims as tasks land.
- MUST size each task for one member and split oversized contracts before spawning - many sequential steps is a sizing failure; size by file or dependency; use `addBlockedBy`/`addBlocks` so the team self-sequences without polling.
- MUST set `owner` on Opus-tier tasks (design, root-cause, judgment); MUST leave mechanical tasks unowned, except a single-seat one (a shared build slot, a single-writer resource) MUST still get an owner at creation.
- A fully-specified plan (gate-passed design, handoff doc, TDD sequence) MUST go on the task list.
- The team SHOULD grow mid-task where the backlog exceeds the roster, or new work fits no existing role.
- A roster spec MUST carry each task's SUBJECT and ID, and MUST be checked against `TaskList` before spawning - a predicted ID may point at the wrong work, or none.
- Only the lead spawns a named teammate; a member needing more hands sends a roster spec, which the lead spawns verbatim.

## Stop teammates once their work is done

- MUST `TaskStop` a teammate by name once its task is complete with nothing queued, not in a later cleanup pass. MAY leave it running only if fresh same-role work is imminent.
- A finished teammate left alive can self-claim the next unowned task, so its owner may name an agent the lead never assigned. MUST check the owner is who you spawned.
- MUST NOT stop a producer that just reported to a peer on its idle ping alone - wait for the consumer to confirm it has every input.
- The lead MUST spawn a fresh replacement for a member reporting high context, not let it continue degraded.

## Persist before ending - `TaskList` does not survive the session

- `TaskList` is session-scoped and lost at session end, deferred items included; a correctly stopped teammate can still leave unclaimed list items.
- Before ending a lead session, MUST run `TaskList` and give every non-completed item a durable home: a memory `task/` entity (`memory.md`), plus `handoff`/`session-end` if work is outstanding.
