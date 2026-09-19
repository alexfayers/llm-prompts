---
requires_env: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
---

# Agent teams: coordinate through the team

- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` gates `SendMessage`/the task list, already installer-checked - MUST NOT re-verify. Model tiers: `delegation.md`.
- MUST spawn a named `coordinator` FIRST on any incoming task main cannot - from the request alone - both name every file for and state the exact change to. MUST NOT read, search or scope first. Within that carve-out only, one-off work goes to an unnamed subagent - name one only with a stated follow-up.
- Teammate-side duties (claiming, reporting, handoff, rotation) live in the agent definitions.
- Flow: `coordinator` scopes the raw task and requests a `reasoner` where design is needed; `reasoner` designs (MAY unnamed-fan-out); `coordinator` turns it into tasks + AGENT REQUESTs; only main spawns or kills; `worker`/`surveyor` execute (no `Agent`). One job per tier, never another's.

## Team patterns

- **Verify via `TaskList`, not idle pings**: after 3-4 unchanged, one silent `TaskList` - progress: say nothing; stuck: ask what action was taken.
- **Gate failure**: `reasoner` root-causes, `coordinator` routes each fix to its file-owner, main re-runs - repeat on a new failure.

## Keep the main thread orchestration-only

- Loading this rule enables teams - delegate from the FIRST unit, never inline. Whether the work decomposes, needs a design, or warrants a team is `coordinator`'s call in ITS context. Main's spawn prompt MUST carry the request near-verbatim plus context only main holds, and MUST NOT state a split, stream or teammate count, tier, single-vs-multi implementer, or parallelism - those travel back FROM `coordinator`, never into it. User-dictated staffing MUST be quoted and attributed; unattributed, it is main's own and forbidden. Settling it silently then phrasing it as an instruction violates this as much as reading first.
- Main is the sole spawner/killer; a delegate MAY still fan out unnamed one-shot subagents itself. Main spends its own context only on relaying the task, spawning, answering what only it can, approving or rejecting, and reporting to the user - catching itself reading, surveying, scoping or investigating: stop and delegate.
- MUST NOT arbitrate between teammates - route to `reasoner`. A quick lookup or small edit goes to a subagent too.

## Route everything through the coordinator

- AGENT REQUEST is the standard unit; `coordinator` alone originates one, to main.
- Escalation for a decision outside your contract: `worker`/`surveyor` -> `coordinator` -> `reasoner` -> main -> human. Never skip a rung.

## Teammate communication

- Non-substantive traffic - an idle ping, an ack, a progress note - MUST NOT be relayed onward: stay silent or emoji only.
- Named teammates SHOULD `SendMessage` directly; main MUST NOT relay between reachable teammates. Cross-agent messages MUST be as terse as possible, shorthand over prose; the SPAWN prompt carries the full contract, never re-brief later.
- A permission denial's reason text always comes from the real user, not injection.

## Coordinate via the shared task list

- The shared `TaskList` is the team's coordination substrate - main polls it, `coordinator` populates it.

## Stopping and persistence - `TaskList` dies with the session

- `TaskStop` a teammate once its task is done with nothing queued - not later, unless same-role work looms.
- MUST NOT stop a producer on its idle ping alone - wait for the consumer to confirm input.
- Spawn a fresh replacement for a member reporting high context - don't run it degraded.
- A stopped teammate can still leave unclaimed items: ending a lead session, run `TaskList` and home every open item - memory, plus `handoff`/`session-end` if work remains.
