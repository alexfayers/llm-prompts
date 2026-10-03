# Delegate complex thought to subagents

- MUST delegate complex thought to an Opus agent, not inline.
- SHOULD match Agent's `model` to the work; name one only where follow-up is expected (`agent-teams.md`).
  - A foreseeable-blocker stop (size/lint gate, permission denial, build slot) implies follow-up - name it to reuse context on retry.
  - **Opus** - design, architecture, root-cause work, debugging, planning, synthesis.
  - **Sonnet** - parallel mechanical work Opus decided: an edit pattern, a bounded search.
  - **Haiku** - trivial work: a lookup, exact change, known shell recipe. Judgment, not file count, sets tier - never with real reasoning.
- A known target (file, symbol, doc you know) is a trivial lookup: SHOULD go to Haiku, or read it yourself if cheaper; MUST NOT let it become "go find out about X". Exception: an active team's delegate-first default (agent-teams.md) overrules this.
- A spawn commits that dimension: MUST NOT resume reads on it or re-read its report - `SendMessage` instead.
- Design/editor agents MUST NOT run tests.

## Who holds `Agent`

- MUST use only named tiers - `reasoner` (Opus, holds `Agent`), `worker` (mechanical), `surveyor` (read-only), `coordinator` (breakdown, `Explore`-only `Agent`); never `general-purpose`.
- `Explore`/`Plan` inherit no rules: their prompt MUST carry every binding constraint; SHOULD prefer `Explore` over `surveyor` for a bounded read-only search.
- Only main spawns a NAMED teammate; roster is flat. `reasoner` MAY fan out unnamed subagents (may recurse), `coordinator` unnamed `Explore` only; else report to `coordinator`, raising the AGENT REQUEST.

## Spawn prompt contract

State the desired change concisely, close to how it was given - MUST NOT spell out mechanics a delegate can work out itself, unless risky/ambiguous. `SendMessage` follows this plus `anti-yap.md`: state the ask/answer, not context it has.

Every spawn prompt, design delegates included, MUST specify:

- source order - local checkout, internal/official docs, public web last - report back if unanswered, never silently widen;
- for a tracked task (memory `task/`, plan slice, ticket): decisions recorded against it - a late one lives only there, not the ticket/plan doc;
- the scope boundary it MUST NOT cross - for remote/live systems, read-only as the ceiling, naming disallowed mutations;
- for lint/formatting/test conventions, package config (`pyproject.toml` or equiv) is authority - MUST match the file it edits, never memory/global preferences;
- where the prompt pins a concrete shape (signature, return type, format) and says match a sibling, MUST reconcile the two, not leave a contradiction to escalate;
- for code/prose, the output-size limit - minimal diff, no unrequested comments, refactors or reformatting, terse report.
- for a UI/visual change: coding.md's rendered check, reported as seen - MUST NOT accept "done" from a test pass or a "folded into another slice" claim.
- for a shell-restricted delegate: name Read/Grep/Glob for investigation, plus exactly which command it MAY still run despite the restriction - an unstated need never authorizes Bash.
- a delegate MUST be asked a question, report the answer - never raw output or verbatim file text - only in a failure, error, or a named value. A drafted edit returns new wording, not current text.

For a code comment, state policy/convention, not draft prose.

- A design/planning prompt MUST route full output to implementers, plus a few lines to main: what changes, what it buys, the risk - no steps/files/rationale. MUST NOT make it main's deliverable.

## Parallelise by default

- SHOULD parallelise whenever work decomposes, design and research included; serial only where step two needs step one's output.
- On an open design question, SHOULD dispatch a few Opus delegates on different angles and synthesize.

## Effort, not model tier

- Effort (`low` to `max`, set in `effort` frontmatter) is the latency and cost lever.
- Unset, a delegate inherits the spawner's effort - a mechanical Sonnet/Haiku SHOULD run `low`/`medium`.
- Within Opus: a quick disagreement or two-option call is `medium`; `high`/`xhigh` only for an architecture decision, hard root cause, or cross-source synthesis.
- `Agent` has no `effort` param - a delegate runs at its `subagent_type`'s pin; `Workflow`'s `agent()` takes `opts.effort`.

## Escalation and waiting

- A delegate stuck on an ambiguity, or needing a user-only preference, SHOULD escalate.
- MUST NOT idle-wait for a background agent/command, `sleep`, or a placeholder call - completion re-invokes you: do other work or end the turn.
- A mid-turn message is silently ignored: wait, or re-verify state yourself. Once idle, `SendMessage` resumes a NAMED delegate - ask for a missing/truncated section, not re-derive it.
- A resend returns a SUMMARY; read its transcript `.jsonl` under `subagents/` - never ask again, MUST NOT re-run the work.
