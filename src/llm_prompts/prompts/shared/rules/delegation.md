---
roles: lead, coordinator, reasoner
targets: claude-code, pi
---

# Delegate complex thought to subagents

- MUST delegate complex thought to {% if AGENT == "pi" %}a judgment agent{% else %}an Opus agent{% endif %}, not inline.
{% if TOOL_AGENT == "delegate_agent" %}
- SHOULD match {{TOOL_AGENT}}'s `model` to the work. A name labels only the live agent.
{% else %}
- SHOULD match {{TOOL_AGENT}}'s `model` to the work; name one only for expected follow-up.
{% endif %}
  - A foreseeable-blocker stop (size/lint gate, permission denial, build slot) implies follow-up: name it.
{% if AGENT == "pi" %}
  - By job, the cheapest installed model that meets it; escalate on evidence. A model is not a role.
  - Judgment (`opus`-class) - design, architecture, root-cause work, debugging, planning, synthesis.
  - Mechanical (`sonnet`-class) - decided parallel work: edit pattern, bounded search.
  - Lookup (`haiku`-class) - a lookup, exact change, known shell recipe; never real reasoning.
{% else %}
  - **Opus** - design, architecture, root-cause work, debugging, planning, synthesis.
  - **Sonnet** - parallel mechanical work Opus decided: edit pattern, bounded search.
  - **Haiku** - trivial work: a lookup, exact change, known shell recipe. Judgment, not file count, sets tier; never real reasoning.
{% endif %}
- A known target (file, symbol, doc) is a trivial lookup: SHOULD go to {% if AGENT == "pi" %}the lookup agent{% else %}Haiku{% endif %}, or read it yourself if cheaper; MUST NOT let it become "go find out about X". 2+ units go to `coordinator`.
- A spawn commits that dimension: MUST NOT resume reads on it or re-read its report; {% if AGENT == "pi" %}`{{TOOL_STEER}}`{% else %}`SendMessage`{% endif %} instead.
- Design/editor agents MUST NOT run tests.

## Who holds `{{TOOL_AGENT}}`

{% if TOOL_AGENT == "delegate_agent" %}
- MUST use only named tiers, passing the `<tier>@<model>:<effort>` name from the tier's description (e.g. `reasoner@opus:high`), never the bare tier - `reasoner` ({% if AGENT == "pi" %}judgment{% else %}Opus{% endif %}), `worker` (mechanical), `surveyor` (read-only), `reviewer` (read-only review), `coordinator` (breakdown, spawns all of these and `Explore`); never `general-purpose`.
{% else %}
- MUST use only named tiers, passing the installed `<tier>-<model>-<effort>` name (e.g. `reasoner-opus-high`), never the bare tier - `reasoner` ({% if AGENT == "pi" %}judgment{% else %}Opus{% endif %}, holds `{{TOOL_AGENT}}`{% if AGENT == "pi" %}, `Explore` only{% endif %}), `worker` (mechanical), `surveyor` (read-only), `coordinator` (breakdown, `Explore`-only `{{TOOL_AGENT}}`); never `general-purpose`.
{% endif %}
- `Explore`/`Plan` inherit no rules: their prompt MUST carry every binding constraint. SHOULD prefer `Explore` over `surveyor` for bounded read-only search.
{% if AGENT == "pi" %}
{% if TOOL_AGENT == "delegate_agent" %}
- Main spawns `coordinator` or `reasoner`; `coordinator` spawns the rest. `Explore` runs foreground, result inline. Children are leaves.
{% else %}
- Only main spawns a NAMED teammate; roster is flat. `reasoner` and `coordinator` MAY spawn unnamed `Explore` only (foreground, result inline); else report to `coordinator` for the AGENT REQUEST.
{% endif %}
{% else %}
- Only main spawns a NAMED teammate; roster is flat. `reasoner` MAY fan out unnamed subagents (may recurse), `coordinator` unnamed `Explore` only; else report to `coordinator` for the AGENT REQUEST.
{% endif %}

## Spawn prompt contract

State the change concisely, not derivable mechanics unless risky/ambiguous. {% if AGENT == "pi" %}`{{TOOL_STEER}}` and `tower_do_talk` follow{% else %}`SendMessage` follows{% endif %} this plus `anti-yap.md`: ask/answer only.

Every spawn prompt MUST specify:

{% if AGENT == "pi" %}
- the memory/MCP facts it needs;
{% endif %}
- source order - local checkout, internal/official docs, public web last - report back if unanswered, never widen silently;
- for a tracked task (memory `task/`, plan slice, ticket): decisions recorded against it;
- the scope boundary it MUST NOT cross - remote/live systems: read-only, naming disallowed mutations;
- lint/formatting/test conventions: package config (`pyproject.toml` or equiv) is authority - MUST match the file edited, not memory/global preferences;
- where the prompt pins a shape (signature, return type, format) and says match a sibling, MUST reconcile the two, not leave a contradiction;
- for code/prose, the output-size limit - minimal diff, no unrequested comments/refactors/reformatting, terse report.
- for a UI/visual change: coding.md's rendered check, reported as seen - MUST NOT accept "done" from a test pass or a "folded into another slice" claim.
- for a shell-restricted delegate: name {% if AGENT == "pi" %}`read`/`grep`/`find`{% else %}Read/Grep/Glob{% endif %} for investigation, plus exactly which command it MAY still run - an unstated need never authorizes {% if AGENT == "pi" %}`bash`{% else %}Bash{% endif %}.
- MUST NOT ask a role without write tools to write files - artifacts go to a `worker`. Scratch notes stay in the report unless a file was requested.
- a delegate asked a question MUST report the answer, never raw output or verbatim file text, except a failure, error or named value. A drafted edit returns new wording only.

- For a code comment, state policy/convention, not draft prose.
- A design/planning prompt MUST route full output to implementers, plus a few lines to main: what changes, what it buys, the risk. MUST NOT make it main's deliverable.

## Parallelise by default

- SHOULD parallelise decomposable work, design and research included; serial only where a step needs prior output.
- On an open design question, SHOULD dispatch a few {% if AGENT == "pi" %}judgment{% else %}Opus{% endif %} delegates on different angles and synthesize.

## Effort, not model tier

- Unset, a delegate inherits the spawner's effort: {% if AGENT == "pi" %}a mechanical/lookup agent SHOULD run `low`/`medium`{% else %}a mechanical Sonnet/Haiku SHOULD run `low`/`medium`{% endif %}.
- Within {% if AGENT == "pi" %}judgment{% else %}Opus{% endif %}: a quick or two-option call is `medium`; `high`/`xhigh` only for architecture, hard root cause, or cross-source synthesis.
- {% if AGENT != "pi" %}`{{TOOL_AGENT}}` has no `effort` param - a{% else %}A{% endif %} delegate runs at its `subagent_type`'s pin{% if TOOL_WORKFLOW %}; `{{TOOL_WORKFLOW}}`'s `agent()` takes `opts.effort`{% if AGENT == "pi" %} (minimal/low/medium/high/xhigh/max){% endif %}{% endif %}.

## Escalation and waiting

- A delegate stuck on ambiguity or needing a user-only preference SHOULD escalate.
- A delegate whose work outgrows its own estimate (more steps, files or phases than assumed) MUST stop and escalate up the ownership edge, stating that more agents may be faster. MUST NOT grind on alone.
- MUST NOT idle-wait on a background agent/command, `sleep` or placeholder - completion re-invokes you; do other work or end the turn.{% if AGENT == "pi" %} Under `pi -p`, MUST `{{TOOL_AGENT_RESULT}}` each background agent first.{% else %} Exception: while a delegate runs, MUST keep a background `sleep 300` armed; if it fires with no update, MUST `SendMessage` it for status.{% endif +%}
{% if AGENT == "pi" %}
{% if TOOL_AGENT == 'delegate_agent' %}
- MUST `continue_agent` a finished agent's exact session for same-scope follow-up (fix, gate retry, missing section), never a fresh delegate/re-derive.
- Results arrive on their own. A `Plan` agent means a named `reasoner`. Outside a Herdr pane `delegate_agent` is unavailable; work inline.
{% else %}
- Resume a finished NAMED delegate with `{{TOOL_AGENT}}` - ask for a missing/truncated section, not a re-derive.
{% endif %}
{% else %}
- A mid-turn message is silently ignored: wait, or re-verify state yourself. Once idle, `SendMessage` resumes a NAMED delegate - ask for a missing/truncated section, not re-derive it.
- A resend returns a SUMMARY; read its transcript `.jsonl` under `subagents/` - MUST NOT ask again or re-run.
{% endif %}
