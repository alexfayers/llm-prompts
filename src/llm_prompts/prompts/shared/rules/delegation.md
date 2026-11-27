---
roles: lead, coordinator, reasoner
targets: claude-code, pi
---

# Delegate complex thought to subagents

- MUST delegate complex thought to {% if AGENT == "pi" %}a judgment agent{% else %}an Opus agent{% endif %}, not inline.
{% if AGENT == "pi" %}
- SHOULD run mechanical or lookup work as a cold worker (`fork` with `model`), judgment work as a warm fork.
{% else %}
- SHOULD match {{TOOL_AGENT}}'s `model` to the work; name one only for expected follow-up, e.g. a foreseeable-blocker stop (size/lint gate, permission denial, build slot).
{% endif %}
{% if AGENT == "pi" %}
  - By job, the cheapest installed model that meets it; escalate on evidence.
  - Judgment (`opus`-class) - design, architecture, root-cause work, debugging, planning, synthesis.
  - Mechanical (`sonnet`-class) - decided parallel work: edit pattern, bounded search.
  - Lookup (`haiku`-class) - a lookup, exact change, known shell recipe; never real reasoning.
{% else %}
  - **Opus** - design, architecture, root-cause work, debugging, planning, synthesis.
  - **Sonnet** - parallel mechanical work Opus decided: edit pattern, bounded search.
  - **Haiku** - trivial work: a lookup, exact change, known shell recipe. Judgment, not file count, sets tier; never real reasoning.
{% endif %}
{% if AGENT == "pi" %}
- A known target (file, symbol, doc) is a trivial lookup: read it yourself, or `fork` a cold worker if cheaper. MUST NOT let it become "find out about X". 2+ units: one `fork` each, in one turn.
- A fork commits that dimension: MUST NOT resume reads on it or re-read its report.
{% else %}
- A known target (file, symbol, doc) is a trivial lookup: SHOULD go to Haiku, or read it yourself if cheaper; MUST NOT let it become "find out about X". 2+ units go to `coordinator`.
- A spawn commits that dimension: MUST NOT resume reads on it or re-read its report; `SendMessage` instead.
{% endif %}
- Design/editor agents MUST NOT run tests.

## Who holds `{{TOOL_AGENT}}`

{% if AGENT == "pi" %}
- Only main and a `team` delegate hold `fork`. Any other delegate MUST NOT fork.
- A `team` forks its own readers and writers, which cannot fork. Its writers' commits land in its worktree, and it reports once.
- A `reader` (default) only reads. A `writer` works only in its own git worktree and its commits land on the current branch - give each branch its own writer.
- A warm fork inherits the session and its rules. A cold worker (`model` set) starts with an empty session: its `task` MUST carry every binding constraint.
{% else %}
- MUST use only named tiers, passing the installed `<tier>-<model>-<effort>` name (e.g. `reasoner-opus-high`), never the bare tier - `reasoner` (Opus, holds `{{TOOL_AGENT}}`), `worker` (mechanical),
  `surveyor` (read-only), `coordinator` (breakdown, `Explore`-only `{{TOOL_AGENT}}`); never `general-purpose`.
- `Explore`/`Plan` inherit no rules: their prompt MUST carry every binding constraint. SHOULD prefer `Explore` to `surveyor` for bounded read-only search.
- Only main spawns a NAMED teammate; roster is flat. `reasoner` MAY fan out unnamed subagents (may recurse), `coordinator` unnamed `Explore` only; else report to `coordinator` for the AGENT REQUEST.
{% endif %}

## Spawn prompt contract

State the change concisely.
State derivable mechanics only if risky or ambiguous.{% if AGENT != "pi" %} {% if AGENT == "pi" %}`{{TOOL_STEER}}` and `tower_do_talk` follow{% else %}`SendMessage` follows{% endif %} this plus
`anti-yap.md`: ask/answer only.{% endif +%}

Every spawn prompt MUST specify:

{% if AGENT == "pi" %}
- the memory/MCP facts it needs;
{% endif %}
- source order - memory, local checkout, internal/official docs, public web last - report back if unanswered, never widen;
- for a tracked task (memory `task/`, plan slice, ticket): its recorded decisions, and that new ones come back in the report, never to memory;
- the scope boundary it MUST NOT cross - remote/live systems: read-only, naming disallowed mutations and PR push permission;
- where the user or another session edits the same files: its own paths, and that it MUST NOT touch or repair others, even half-written;
- lint/format/test conventions: package config (e.g. `pyproject.toml`) outranks memory/global preferences - MUST match the file edited;
- where the prompt pins a shape (signature, return type, format) and says match a sibling, MUST reconcile the two;
- for code/prose, the output-size limit - minimal diff, no unrequested comments/refactors/reformatting, terse report.
- for a UI/visual change: coding.md's rendered check, reported as seen - MUST NOT accept "done" from a test pass or "folded into another slice".
- for a shell-restricted delegate: name {% if AGENT == "pi" %}`read`/`grep`/`find`{% else %}Read/Grep/Glob{% endif %} for investigation, and exactly which command it MAY run -
  never implicit {% if AGENT == "pi" %}`bash`{% else %}Bash{% endif %}.
- MUST NOT ask a role without write tools to write files - artifacts go to a `{% if AGENT == "pi" %}writer{% else %}worker{% endif %}`. Scratch notes stay in the report unless a file is requested.
- a delegate asked a question MUST report the answer, not raw output/file text (except failure, error or named value). A drafted edit returns new wording only.
- For a code comment, state policy/convention, not draft prose.
- A design/planning prompt MUST route full output to implementers, plus a few lines to main: what changes, what it buys, the risk. MUST NOT make it main's deliverable.

## Parallelise by default

- SHOULD parallelise decomposable work, design/research included; serial only if a step needs prior output.
- On an open design question, SHOULD dispatch a few {% if AGENT == "pi" %}judgment{% else %}Opus{% endif %} delegates on different angles and synthesize.

{% if AGENT == "pi" %}
## Reuse a warm fork

- SHOULD give a finished fork whose cache is warm and whose context is low its next task with `fork_resume`, not start a cold fork - cheaper.
  The `fork` result lists each such fork with its context and cache time left.
- MUST start cold only when no warm fork holds the context, or when the warm fork's context costs more than a cold start.
- SHOULD use `from` and `shared` mainly to start several forks on one base.

{% endif %}
## Effort, not model tier

- Unset, a delegate inherits the spawner's effort: {% if AGENT == "pi" %}a mechanical/lookup agent SHOULD run `low`/`medium`{% else %}a mechanical Sonnet/Haiku SHOULD run `low`/`medium`{% endif %}.
- Within {% if AGENT == "pi" %}judgment{% else %}Opus{% endif %}: a quick or two-option call is `medium`; `high`/`xhigh` only for architecture, hard root cause, cross-source synthesis.
{% if AGENT == "pi" %}
- A warm fork runs at main's model and effort. A cold worker runs at its `model`'s `:<effort>` suffix.
{% else %}
- {% if AGENT != "pi" %}`{{TOOL_AGENT}}` has no `effort` param - a{% else %}A{% endif %} delegate runs at its `subagent_type`'s pin{% if TOOL_WORKFLOW %};
  `{{TOOL_WORKFLOW}}`'s `agent()` takes `opts.effort`{% if AGENT == "pi" %} (minimal/low/medium/high/xhigh/max){% endif %}{% endif %}.
{% endif %}

## Escalation and waiting

- A delegate stuck on ambiguity or needing a user preference SHOULD escalate.
- MUST stop a review loop per `pr-review`'s `review-loop.md`.
- A delegate whose work outgrows its estimate (steps/files/phases) MUST stop and escalate to its owner, noting more agents may help.
- MUST NOT idle-wait on a background agent/command, `sleep` or placeholder - completion re-invokes you; work or end turn.{% if AGENT != "pi" %} Exception: while any delegate runs,
  MUST keep ONE background `sleep 300` armed per session. On firing, MUST `SendMessage` each delegate silent since arming for status, then re-arm.{% endif +%}
{% if AGENT != "pi" %}
- A mid-turn message is ignored: wait or re-verify. Once idle, `SendMessage` resumes a NAMED delegate - ask for a missing/truncated section, not re-derive.
- A resend returns a SUMMARY; read its transcript `.jsonl` under `subagents/` - MUST NOT re-ask/re-run.
{% endif %}
