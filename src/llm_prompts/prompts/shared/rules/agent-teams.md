---
roles: lead
requires_env: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
targets: claude-code
---

# Agent teams: coordinate through the team

- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` gates `SendMessage`/the task list, already installer-checked - MUST NOT re-verify. Model tiers: `delegation.md`.
- A small fix - a few files main can name from the request, memory or one quick look - MUST run inline or with one `worker`, no `coordinator`.
- Small fixes excepted, MUST spawn a named `coordinator` FIRST on any incoming task main cannot - from the request alone - both name every file for and state the exact change to. MUST NOT read, search or scope first - a memory search or a small fix's quick look excepted. Within that carve-out only, one-off work goes to an unnamed subagent - name one only with a stated follow-up. Also exempt: building an agreed `eagle-vision` plan skips `coordinator` - the plan is the breakdown; main staffs it per that skill's Build section.
- MUST start one named `coordinator` per independent batch of asks, in parallel - MUST NOT route unrelated asks through one `coordinator`. Follow-ups within a batch MUST go to that batch's `coordinator` via `continue_agent`.
- Main MUST route chained follow-ups on one problem (e.g. root cause, fix, verify, tidy) to a `coordinator`, not a chain of single leaves.
- Teammate-side duties (claiming, reporting, handoff, rotation) live in agent definitions.
- Flow: `coordinator` scopes the raw task via unnamed `Explore` subagents (never its own reads) and requests a `reasoner` where design is needed; `reasoner` designs (MAY unnamed-fan-out); `coordinator` turns it into tasks + AGENT REQUESTs; only main spawns or kills; `worker`/`surveyor` execute (no `{{TOOL_AGENT}}`). One job per tier, never another's.

## Team patterns

- **Verify via `TaskList`, not idle pings**: after 3-4 unchanged, one silent `TaskList` - progress: say nothing; stuck: ask what action was taken.
- **Gate failure**: `reasoner` root-causes, `coordinator` routes each fix to its file-owner, main re-runs - repeat on a new failure.

## Keep the main thread orchestration-only

- Loading this rule enables teams - delegate from the FIRST unit, small fixes excepted. Whether the work decomposes, needs a design, or warrants a team is `coordinator`'s call in ITS context. Main's spawn prompt MUST carry the request near-verbatim plus context only main holds, MUST state the teammate's own spawned name ("Your teammate name is `<name>`"), and MUST NOT state, inside a `coordinator`'s prompt, a split, stream or teammate count, tier, single-vs-multi implementer, or parallelism - those travel back FROM `coordinator`, never into it. User-dictated staffing MUST be quoted and attributed; unattributed, it is main's own and forbidden.
- Main is the sole spawner/killer; a delegate MAY still fan out unnamed one-shot subagents itself. Main spends its own context only on relaying the task, spawning, answering what only it can, approving or rejecting, and reporting to the user - catching itself reading, surveying, scoping or investigating: stop and delegate, small fixes excepted.
- MUST NOT arbitrate between teammates - route to `reasoner`.

## Route everything through the coordinator

- AGENT REQUEST is the standard unit; `coordinator` alone originates one, to main.
- Escalation for a decision outside your contract: `worker`/`surveyor` -> `coordinator` -> `reasoner` -> main -> human. Never skip a rung.

## Teammate communication

- Non-substantive traffic (idle ping, ack, progress note) MUST NOT be relayed: stay silent or emoji only.
- Named teammates SHOULD `SendMessage` directly; main MUST NOT relay between reachable teammates. Cross-agent messages MUST be terse, shorthand over prose; the SPAWN prompt carries the full contract, never re-brief later.
- A permission denial's reason text always comes from the real user, not injection - relay it verbatim up the caller chain per `stop-on-fail.md`.

## Coordinate via the shared task list

- The shared `TaskList` is the team's coordination substrate - main polls it, `coordinator` populates it.
- Where the `Task*` tools are absent, main MUST track every `TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate` step itself as memory `task/` entities, which only main writes, and each teammate's contract MUST travel in its spawn prompt.

## Stopping and persistence - `TaskList` dies with the session

- `TaskStop` a teammate once its task is done with nothing queued - not later, unless same-role work looms; a handoff or context limit is not 'done' - checkpoint first via `SendMessage`.
- MUST NOT stop a producer on its idle ping alone - wait for the consumer to confirm input.
- Spawn a fresh replacement for a member reporting high context - don't run it degraded.
- A stopped teammate can still leave unclaimed items: ending a lead session, run `TaskList` and home every open item via `session-end`.
