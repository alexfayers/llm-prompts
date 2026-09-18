# Delegate complex thought to subagents

- MUST delegate complex thought to an Opus agent, not inline.
- SHOULD match the Agent tool's `model` to the work; name an agent only where follow-up is expected (`agent-teams.md`).
  - Stopping to report a foreseeable blocker (size/lint gate, permission denial, build slot) implies follow-up - name it so retry reuses context.
  - **Opus** - design, architecture, root-cause, debugging, planning, synthesis.
  - **Sonnet** - parallel mechanical work Opus decided: an edit pattern, a bounded search.
  - **Haiku** - trivial work: a lookup, a known exact change, a known shell recipe. Judgment, not file count, sets the tier - never where reasoning is involved.
- A known target (file, symbol, doc) is a trivial lookup: SHOULD go to Haiku, or read it yourself if cheaper; MUST NOT let it become "go find out about X". Exception: agent-teams.md's delegate-from-the-first-unit default overrules this when a team is active.
- A spawn commits that dimension: MUST NOT resume your reads on it or re-read its report - `SendMessage` instead.
- Design/editor agents MUST NOT run tests; the lead holds that gate.

## Delegates never hold `Agent`

- MUST use only subagent types withholding `Agent` - `reasoner`/`architect` (Opus), `worker` (mechanical), `surveyor` (read-only); never `general-purpose`.
- `Explore`/`Plan` inherit no rules: their prompt MUST carry every binding constraint; SHOULD prefer `Explore` over `surveyor` for a bounded read-only search.
- Spawning and coordination stay with main; a delegate needing more hands reports back.

## Spawn prompt contract

State the desired change concisely, close to how it was given - MUST NOT spell out mechanics a delegate can work out itself, unless ambiguous or risky. `SendMessage` follows this plus `anti-yap.md`'s terseness: state the ask/answer, not context the delegate already has.

Every spawn prompt, design delegates included, MUST specify:

- source order - local checkout, internal/official docs, public web last - report back if they don't answer, never silently widen the search;
- for a tracked task (memory `task/`, plan slice, ticket): decisions recorded against it - a late one lives only there, not the ticket/plan doc;
- the scope boundary it MUST NOT cross - for remote/live systems, read-only as the ceiling, naming disallowed mutations;
- for lint/formatting/test conventions, the package config (`pyproject.toml` or equivalent) is authority - MUST match the file it edits, never memory/global preferences;
- where the prompt pins a concrete shape (signature, return type, format) and says match a sibling, MUST reconcile the two, not leave a contradiction to escalate;
- for code or prose, the output-size limit - minimal diff, no unrequested comments, refactors or reformatting, terse report.
- for a shell-restricted delegate: name Read/Grep/Glob for investigation, plus exactly which command it MAY still run despite the restriction - an unstated need never authorizes Bash.
- a delegate MUST be asked a question, report the answer - never raw output or verbatim file text - only in a failure, error, or a named value. A drafted edit returns new wording, not current text.

For a code comment, state policy/convention, not draft prose - unless it names an in-repo exemplar (beats "no comments"); check first.

- A design/planning prompt MUST route full output to implementers, plus a few lines to main: what changes, what it buys, the risk - no steps/files/rationale. MUST NOT make it main's deliverable.

## Parallelise by default

- SHOULD parallelise whenever work decomposes, design and research included; serial only where step two needs step one's output.
- On an open design question, SHOULD dispatch a few Opus delegates on different angles and synthesize.

## Effort, not model tier

- Effort - `low`/`medium`/`high`/`xhigh`/`max`, set in its `effort` frontmatter - is the latency and cost lever.
- Unset, a delegate inherits the spawner's effort - a mechanical Sonnet/Haiku SHOULD run `low`/`medium`.
- Within Opus: a quick disagreement or two-option call is `medium`; `high`/`xhigh` only for an architecture decision, non-obvious root cause, or cross-source synthesis.
- The `Agent` tool has no `effort` parameter - a delegate runs at what its `subagent_type` pins; `Workflow`'s `agent()` takes `opts.effort`.

## Escalation and waiting

- A delegate stuck on an ambiguity, or needing a user-only preference, SHOULD escalate to main.
- MUST NOT idle-wait for a background agent/command, `sleep`, or a placeholder call - completion re-invokes you: do other work or end the turn.
- A mid-turn message is silently ignored: wait, or re-verify state yourself. Once idle, `SendMessage` resumes a NAMED delegate - ask for a missing/truncated section, not re-derive it.
- A resend returns a SUMMARY; read its transcript `.jsonl` under `subagents/` - never ask again, MUST NOT re-run the work.
