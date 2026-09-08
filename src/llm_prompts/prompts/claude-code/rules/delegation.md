# Delegate complex thought to subagents

- MUST delegate complex thought to an Opus agent, not inline.
- SHOULD match the Agent tool's `model` to the work; name an agent only where follow-up is expected (`agent-teams.md`).
  - Where the prompt tells the delegate to stop and report on a foreseeable blocker (size/lint gate, permission denial, build slot), follow-up IS expected - name it, so retry reuses context instead of re-briefing fresh.
  - **Opus** - design, architecture, root-cause work, debugging, planning, synthesis.
  - **Sonnet** - parallel mechanical work Opus decided: an edit pattern, a bounded search.
  - **Haiku** - trivial work: a lookup, a known exact change, a known shell recipe. Judgment, not file count, sets the tier - never where reasoning is involved.
- A known target (file, symbol, doc you know) is a trivial lookup: SHOULD go to Haiku, or read it yourself if a spawn costs more; MUST NOT let it become "go find out about X".
- A spawn commits that dimension: MUST NOT resume your reads on it or re-read its report - `SendMessage` instead.
- Design/editor agents MUST NOT run tests; the lead holds that gate.

## Delegates never hold `Agent`

- MUST use only subagent types withholding `Agent` - `reasoner`/`architect` (Opus), `worker` (mechanical), `surveyor` (read-only); never a catch-all (`general-purpose`).
- `Explore`/`Plan` inherit no rules: their prompt MUST carry every binding constraint; SHOULD prefer `Explore` over `surveyor` for a bounded read-only search.
- Spawning and coordination stay with main; a delegate needing more hands reports back.

## Spawn prompt contract

Every spawn prompt, design delegates included, MUST specify:

- sources in order - local checkout, internal/official docs, public web last - report back where they don't answer, never silently widen the search;
- for a tracked task (memory `task/`, plan slice, ticket), the decisions recorded against it - a late one lives only there, not the ticket or plan doc;
- the scope boundary it MUST NOT cross - for remote/live systems, read-only as the ceiling, naming the mutations it MUST NOT make;
- for lint/formatting/test conventions, the package's config (`pyproject.toml` or equivalent) as authority - MUST match the file it edits, never memory or global preferences;
- where the prompt pins a concrete shape (signature, return type, format) and says match a sibling, MUST reconcile the two, not leave the delegate a contradiction to escalate;
- for code or prose, the output-size limit - minimal diff, no unrequested comments, refactors or reformatting, terse report.
- for a shell-restricted delegate: name Read/Grep/Glob for investigation, and name exactly any command it MAY still run despite the restriction - an unstated need (e.g. deleting a file) never itself authorizes Bash.
- a delegate MUST be asked a question and report the answer, never raw command output or verbatim file text - either belongs only in a failure, error, or a value the asker named. For a drafted edit, return the new wording, not the current text.

For a code comment, state policy and project convention, not draft prose - unless the prompt names an in-repo exemplar, whose conventions beat a blanket "no comments"; check it first, and a delegate flagging a clash is right.

- A design/planning prompt MUST route its full output to implementers, and separately require a few lines to main: what changes, what it buys, the risk - zero-context reader, no steps/files/rationale. MUST NOT make the plan main's deliverable.

## Parallelise by default

- SHOULD parallelise whenever work decomposes, design and research included; serial only where step two needs step one's output.
- On an open design question, SHOULD dispatch a few Opus delegates on different angles and synthesize.

## Effort, not model tier

- Effort - `low`/`medium`/`high`/`xhigh`/`max`, set in its `effort` frontmatter - is the latency and cost lever.
- Unset, a delegate inherits the spawner's effort - a mechanical Sonnet/Haiku SHOULD run `low`/`medium`.
- Within Opus: a quick disagreement or two-option call is `medium`; `high`/`xhigh` only for an architecture decision, a non-obvious root cause, or synthesis across conflicting sources.
- The `Agent` tool has no `effort` parameter - a delegate runs at what its `subagent_type` pins; `Workflow`'s `agent()` takes `opts.effort`.

## Escalation and waiting

- A delegate stuck on an ambiguity, or needing a user-only preference, SHOULD escalate through main.
- MUST NOT idle-wait for a background agent/command, `sleep`, or a placeholder call - completion re-invokes you: do other work or end the turn.
- A mid-turn message is silently ignored: MUST wait or re-verify state yourself. Once idle, `SendMessage` resumes a NAMED delegate - ask it for a missing/truncated section, never re-derive it.
- A resend returns a SUMMARY, since it thinks it already reported. After one, MUST read its transcript `.jsonl` under `subagents/`, never ask again, and MUST NOT re-run the work.
