# Delegate complex thought to subagents

- MUST delegate complex thought to an Opus agent, not inline.
- SHOULD match the Agent tool's `model` to the work; name an agent only where follow-up is expected (`agent-teams.md`).
  - Where the spawn prompt itself tells the delegate to stop and report on a foreseeable blocker (a size or lint gate, a permission denial, a build slot), follow-up IS expected - MUST name it, so the retry reuses its context instead of re-briefing a fresh one.
  - **Opus** - design, architecture, root-cause work, debugging, planning, synthesis.
  - **Sonnet** - parallel mechanical work Opus decided: an edit pattern, a bounded search.
  - **Haiku** - trivial work: a lookup, a known exact change, a known shell recipe. Judgment, not file count, sets the tier; MUST NOT use where reasoning is involved.
- A known target (file, symbol, doc you know) is one trivial lookup: SHOULD go to Haiku, or read it yourself where a spawn costs more; MUST NOT let it become "go find out about X".
- A spawn commits that dimension: MUST NOT resume your reads on it or re-read its report - `SendMessage` instead.
- Design and editor agents MUST NOT run tests; the lead holds that gate.

## Delegates never hold `Agent`

- MUST use only subagent types withholding `Agent` - `reasoner`/`architect` (Opus judgment), `worker` (mechanical), `surveyor` (read-only); MUST NOT use a catch-all (`general-purpose`).
- `Explore`/`Plan` inherit no rules: their prompt MUST carry every binding constraint; SHOULD prefer `Explore` over `surveyor` for a bounded read-only search.
- Spawning and coordination stay with main; a delegate needing more hands reports back.

## Spawn prompt contract

Every spawn prompt, design delegates included, MUST specify:

- sources in order - local checkout, internal or official docs, public web last - to report back where they do not answer, never silently widen the search;
- for a tracked task (memory `task/`, plan slice, ticket), the decisions recorded against it - a late one lives only there, not the ticket or plan doc;
- the scope boundary it MUST NOT cross, and for remote/live systems read-only as the ceiling, naming the mutations it MUST NOT make;
- for lint, formatting or test conventions, the package's config (`pyproject.toml` or equivalent) as authority - MUST match the file it edits, never memory or global preferences;
- for code or prose, the output-size limit - minimal diff, no unrequested comments, refactors or reformatting, terse report.
- a delegate MUST be asked a question and MUST report the answer, never raw command output or verbatim file text; either belongs only in a failure, an error, or a value the asker named. Where the point is to draft an edit, the delegate MUST return the proposed new wording, not the current text.

For a code comment, MUST state policy and project convention, not draft prose - unless the prompt names an in-repo exemplar, whose conventions beat a blanket "no comments"; MUST check it first, and a delegate flagging a clash is right.

- A design or planning prompt MUST route its full output to implementers, and MUST separately require a few lines to main: what changes, what it buys, the risk - zero-context reader, no steps, files or rationale. MUST NOT make the plan main's deliverable.

## Parallelise by default

- SHOULD parallelise whenever work decomposes, design and research included; serial only where step two needs step one's output.
- On an open design question, SHOULD dispatch a few Opus delegates on different angles and synthesize.

## Effort, not model tier

- Effort - `low`/`medium`/`high`/`xhigh`/`max`, set in its `effort` frontmatter - is the latency and cost lever.
- Unset, a delegate inherits the spawner's effort, so a mechanical Sonnet or Haiku SHOULD run `low`/`medium`.
- Within Opus: a quick disagreement or two-option call is `medium`; `high`/`xhigh` only for an architecture decision, a non-obvious root cause, or synthesis across conflicting sources.
- The `Agent` tool has no `effort` parameter - a delegate runs at what its `subagent_type` pins; `Workflow`'s `agent()` takes `opts.effort`.

## Escalation and waiting

- A delegate stuck on an ambiguity, or needing a user-only preference, SHOULD escalate through main.
- MUST NOT idle-wait for a background agent or command, `sleep`, or issue a placeholder call - a completion re-invokes you: do other work or end the turn.
- A mid-turn message is silently ignored: MUST wait or re-verify state yourself. Once idle, `SendMessage` resumes a NAMED delegate - MUST ask it for a missing or truncated section, never re-derive it.
- A resend returns a SUMMARY, since it thinks it already reported. After one, MUST read its transcript `.jsonl` under `subagents/`, never ask again, and MUST NOT re-run the work.
