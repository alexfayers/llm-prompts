---
requires_env: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
---

# Agent teams: coordinate through the team

- Requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, which gates direct `SendMessage` between named teammates and the shared task list. The installer already checked it; MUST NOT re-verify with a shell command. See `delegation.md` for model-tier selection.
- A named team SHOULD be the default rather than reserved for an explicit ask - research, multi-step design, parallel edits, verification.
- When standing up a team, MUST load the `agent-team-patterns` skill first - it carries the survey/sub-lead pipeline, multiple sub-leads, and verifying sub-lead progress.
- Teammate-side duties - claiming, reporting, handing off, asking to be rotated out - live in the agent definition bodies, not here.

## Keep the main thread orchestration-only

- Main spins up the team, assigns work via the task list and checks final results. It MUST NOT do delegable work itself, and MUST stop and delegate the moment it catches itself reading a file, writing code or investigating.
- Main MUST use only `Agent`, `SendMessage`, the `Task*` tools, and light verification - reading what a teammate produced. MUST NOT re-run a mechanical command (`git status`/`find`/a build) to double-check.
- MUST NOT arbitrate between teammates - route the call to a named Opus delegate.
- No exception for a quick lookup (`find`/`grep`/`ls`/status): MUST route it to a standing Haiku teammate.
- No exception for a judgment-bearing skill (e.g. `refine-plan`), even via a slash command: MUST spawn a teammate to run it.

## Only surface substantive teammate updates

- MUST NOT relay `idle_notification` pings to the user - stay silent, or send a single emoji and nothing else.
- MUST surface a teammate message only when substantive: a result, a question needing user input, or a blocker.
- `idleReason: "available"` means the teammate has stopped and sends nothing unsolicited, even holding a finished result - `SendMessage` it if you need status.

## Let the team talk to each other

- Named teammates SHOULD `SendMessage` each other directly - an Opus designer hands work straight to Sonnet workers.
- Main MUST NOT relay between two teammates that can reach each other.

## Coordinate through the shared task list

- Delegated work SHOULD default to `TaskCreate`, created the moment there is more than one independent piece, not once full scope is known.
- Main creates and refines tasks; it MUST NOT claim or execute them.
- SHOULD spawn teammates for expected roles before the list is full, so a standing team self-claims as tasks land.
- MUST size each task for one member, and MUST split an oversized contract before spawning. Many sequential steps is a sizing failure - size by file or dependency. Use `addBlockedBy`/`addBlocks` so the team self-sequences without polling.
- MUST set `owner` on Opus-tier tasks (design, root-cause, judgment); MUST leave mechanical tasks unowned.
- A fully-specified plan (gate-passed design, handoff doc, TDD sequence) MUST still go on the task list.
- The team SHOULD grow mid-task when the backlog exceeds the roster or new work fits no existing role.
- A roster spec MUST carry each task's SUBJECT as well as its ID, and MUST be checked against `TaskList` before spawning - a predicted ID points at the wrong work or at nothing.
- Only the lead spawns a named teammate. A member needing more hands sends a roster spec, which the lead spawns verbatim.

## Set teammate effort, don't inherit it

- Effort is separate from model tier and is the lever on latency. For a mechanical teammate, SHOULD pick a `subagent_type` whose frontmatter pins low/medium effort. See `delegation.md`.

## Stop teammates once their work is done

- MUST `TaskStop` a teammate by name once its task is complete with nothing queued, not in a later cleanup pass. MAY leave it running only if fresh same-role work is imminent.
- A finished teammate left alive will self-claim the next unowned task in its area, so an owner field can name an agent the lead never assigned. MUST check the owner is the agent you spawned.
- MUST NOT stop a producer that just reported to a peer on its own idle ping alone - wait for the consumer to confirm it has every expected input.
- The lead MUST spawn a fresh replacement for a member that reports high context, rather than let it continue degraded.

## Persist before ending - the shared TaskList does not survive the session

- `TaskList` is session-scoped and lost at session end, deferred items included.
- Before ending a lead session, MUST run `TaskList` and give every non-completed item a durable home: a memory `task/` entity (see `memory.md`), plus the `handoff`/`session-end` skill if work is outstanding.
- A correctly stopped teammate can still leave unclaimed list items.
