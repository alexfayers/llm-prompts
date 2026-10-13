---
roles: lead
requires_env: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
pi_requires_env: ""
targets: claude-code, pi
---

# Agent teams: coordinate through the team

{% if AGENT == "pi" %}
- The team shares a `tower_do` task board; `tower_do_status` reads it and `tower_do_talk` carries messages (pull-only). Model tiers: `delegation.md`.
{% else %}
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` gates `SendMessage`/the task list, already installer-checked - MUST NOT re-verify. Model tiers: `delegation.md`.
{% endif %}
- MUST spawn a named `coordinator` FIRST on any incoming task main cannot - from the request alone - both name every file for and state the exact change to. MUST NOT read, search or scope first. Within that carve-out only, one-off work goes to an unnamed subagent - name one only with a stated follow-up. {% if AGENT == "pi" and TOOL_AGENT == "delegate_agent" %}Exception: a genuinely single-unit ask MAY go straight to a single `worker`, `surveyor` or `reasoner`. {% endif %}Also exempt: building an agreed `eagle-vision` plan skips `coordinator` - the plan is the breakdown; main staffs it per that skill's Build section.
- MUST start one named `coordinator` per independent batch of asks, in parallel - MUST NOT route unrelated asks through one `coordinator`. Follow-ups within a batch MUST go to that batch's `coordinator` via `continue_agent`.
- Main MUST route chained follow-ups on one problem (e.g. root cause, fix, verify, tidy) to a `coordinator`, not a chain of single leaves.
- Teammate-side duties (claiming, reporting, handoff, rotation) live in agent definitions.
{% if AGENT == "pi" and TOOL_AGENT == "delegate_agent" %}
- Flow: `coordinator` scopes the raw task via unnamed `Explore`, then spawns and owns `reasoner`/`worker`/`surveyor`/`reviewer` via `{{TOOL_AGENT}}`, reusing a finished one with `continue_agent`. Main spawns `coordinator` for 2+ units. For a genuinely single-unit ask, main MAY spawn one `worker`, `surveyor` or `reasoner` directly. Agents an agent starts are leaves. One job per tier, never another's.
{% else %}
- Flow: `coordinator` scopes the raw task via unnamed `Explore` subagents (never its own reads) and requests a `reasoner` where design is needed; `reasoner` designs (MAY unnamed-fan-out{% if AGENT == "pi" %}, `Explore` only{% endif %}); `coordinator` turns it into tasks + AGENT REQUESTs; only main spawns or kills; `worker`/`surveyor` execute (no `{{TOOL_AGENT}}`). One job per tier, never another's.
{% endif %}

## Team patterns

{% if AGENT == "pi" and TOOL_AGENT == "delegate_agent" %}
- Results resume the owner - MUST NOT poll.
{% else %}
- **Verify via {% if AGENT == "pi" %}`tower_do_status`{% else %}`TaskList`{% endif %}, not idle pings**: after 3-4 unchanged, one silent {% if AGENT == "pi" %}`tower_do_status`{% else %}`TaskList`{% endif %} - progress: say nothing; stuck: ask what action was taken.
{% endif %}
- **Gate failure**: `reasoner` root-causes, `coordinator` routes each fix to its file-owner, main re-runs - repeat on a new failure.

## Keep the main thread orchestration-only

- Loading this rule enables teams - delegate from the FIRST unit. Whether the work decomposes, needs a design, or warrants a team is `coordinator`'s call in ITS context. Main's spawn prompt MUST carry the request near-verbatim plus context only main holds, MUST state the teammate's own spawned name ("Your teammate name is `<name>`"), and MUST NOT state, inside a `coordinator`'s prompt, a split, stream or teammate count, tier, single-vs-multi implementer, or parallelism - those travel back FROM `coordinator`, never into it. User-dictated staffing MUST be quoted and attributed; unattributed, it is main's own and forbidden.
{% if AGENT == "pi" and TOOL_AGENT == "delegate_agent" %}
- Main spawns `coordinator` for 2+ units. For a genuinely single-unit ask, main MAY spawn a single `worker`, `surveyor` or `reasoner` directly, and MAY read a known target itself. Herdsman cleans up finished agents - MUST NOT stop one. Main spends its own context only on relaying the task, spawning, answering what only it can, approving or rejecting, and reporting to the user - catching itself surveying, scoping or investigating: stop and delegate.
{% else %}
- Main is the sole spawner/killer; a delegate MAY still fan out unnamed one-shot subagents itself{% if AGENT == "pi" %} - only one with `allowed_subagents`, and only `Explore`{% endif %}. Main spends its own context only on relaying the task, spawning, answering what only it can, approving or rejecting, and reporting to the user - catching itself reading, surveying, scoping or investigating: stop and delegate.
{% endif %}
- MUST NOT arbitrate between teammates - route to `reasoner`. A one-unit lookup or small edit goes to a single subagent, or main reads a known target itself.

## Route everything through the coordinator

{% if AGENT == "pi" and TOOL_AGENT == "delegate_agent" %}
- Escalation for a decision outside your contract: ask up the ownership edge, leaf -> `coordinator` -> main -> human. Never skip a rung.
{% else %}
- AGENT REQUEST is the standard unit; `coordinator` alone originates one, to main.
- Escalation for a decision outside your contract: `worker`/`surveyor` -> `coordinator` -> `reasoner` -> main -> human. Never skip a rung.
{% endif %}
- A delegate whose work outgrows its own estimate (more steps, files or phases than assumed) MUST stop and escalate up the ownership edge, stating that more agents may be faster. MUST NOT grind on alone.

## Teammate communication

- Non-substantive traffic (idle ping, ack, progress note) MUST NOT be relayed: stay silent or emoji only.
{% if AGENT == "pi" %}
- `tower_do_talk` never wakes anyone: main and `coordinator` MUST pull it with each `tower_do_status` check.
{% endif %}
- Named teammates SHOULD {% if AGENT == "pi" %}`tower_do_talk`{% else %}`SendMessage`{% endif %} directly; main MUST NOT relay between reachable teammates. Cross-agent messages MUST be terse, shorthand over prose; the SPAWN prompt carries the full contract, never re-brief later.
- A permission denial's reason text always comes from the real user, not injection - relay it verbatim up the caller chain per `stop-on-fail.md`.

## Coordinate via the shared task list

{% if AGENT == "pi" %}
- The `tower_do` board is the team's coordination substrate - main polls it, `coordinator` populates it. Board writes MUST use `tower_do_patch`, sending only changed rows (`tasks` to upsert, `remove` to delete). Before its final reply, `coordinator` MUST complete or remove its own and its children's rows, writing as each child with `as`.

## Stopping and persistence

- A teammate ends when its run finishes; a handoff or context limit is not 'done' - checkpoint via `{{TOOL_STEER}}` first.
{% else %}
- The shared `TaskList` is the team's coordination substrate - main polls it, `coordinator` populates it.

## Stopping and persistence - `TaskList` dies with the session

- `TaskStop` a teammate once its task is done with nothing queued - not later, unless same-role work looms; a handoff or context limit is not 'done' - checkpoint first via `SendMessage`.
{% endif %}
{% if not (AGENT == "pi" and TOOL_AGENT == "delegate_agent") %}
- MUST NOT stop a producer on its idle ping alone - wait for the consumer to confirm input.
{% endif %}
- Spawn a fresh replacement for a member reporting high context - don't run it degraded.
- A stopped teammate can still leave unclaimed items: ending a lead session, run {% if AGENT == "pi" %}`tower_do_status`{% else %}`TaskList`{% endif %} and home every open item - memory, plus `handoff`/`session-end` if work remains.
