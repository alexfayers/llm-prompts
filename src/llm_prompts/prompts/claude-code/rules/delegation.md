# Delegate complex thought to subagents

- MUST delegate complex thought to an Opus agent, not inline.
- SHOULD match the Agent tool's `model` to the work; name an agent only where follow-up is expected (`agent-teams.md`).
  - **Opus** - design, architecture, root-cause investigation, debugging, planning, synthesis.
  - **Sonnet** - parallel mechanical execution: an edit pattern Opus designed, a bounded search, a decided step.
  - **Haiku** - genuinely trivial work: a lookup, a one-line transform or known exact change across files, mechanical shell commands with a known recipe - judgment, not file count, raises the tier; MUST NOT use it where real reasoning is involved.
- A known target - a file, symbol or doc you already know - is one trivial lookup: SHOULD go to Haiku, or be read directly where a spawn costs more. MUST NOT let it become "go find out about X".
- A spawn commits that dimension: MUST NOT resume your own reads on it, nor re-read what its report covered - `SendMessage` instead.
- Design and editor agents MUST NOT run tests; the lead holds that gate.

## Delegates never hold `Agent`

- MUST use only subagent types withholding `Agent`: `reasoner`/`architect` for Opus judgment, `worker` for mechanical work, `surveyor` for read-only research. MUST NOT use a catch-all (`general-purpose`).
- `Explore`/`Plan` inherit no rules, so their prompt MUST carry every constraint that matters; SHOULD prefer `Explore` over `surveyor` for a bounded read-only search.
- Spawning and coordination stay with main; a delegate needing more hands reports back.

## Spawn prompt contract

Every spawn prompt, design delegates included, MUST specify:

- the exact sources in order - local checkout, internal or official docs, public web last - and, where they do not answer, report back, never silently widen the search;
- for a delegate executing a tracked task (memory `task/`, plan slice, ticket), the decisions recorded against it - one taken after it was opened lives only there, not in the ticket body or plan doc;
- the scope boundary it MUST NOT go beyond, and for remote/live systems, that read-only is the ceiling, naming the mutating actions it MUST NOT take;
- for lint, formatting or test conventions, the package's own config (`pyproject.toml` or equivalent) as the authority, and that it MUST match the file it edits - never memory or global preferences;
- for code or prose, the output-size constraint - minimal diff, no unrequested comments, refactors or reformatting, terse report.
- a command-running delegate MUST be asked a question and MUST report the answer, never the command's raw output; verbatim output belongs only in a failure, an error, or a value the asker named. Where the requester can search the tree itself, file-finding MUST NOT go to the runner at all.

For a code comment, MUST state the policy and the project's convention, not draft prose - unless the prompt names an in-repo exemplar, whose conventions beat a blanket "no comments"; MUST check it first, and a delegate flagging the clash is right.

- A design or planning delegate's prompt MUST route its full output to the implementers, and MUST separately require a few lines back to main: what is changing, what it buys, the risk - zero-context reader, no steps, files or rationale. MUST NOT make the plan main's deliverable.

## Parallelise by default

- SHOULD parallelise whenever work decomposes, design and research included; serial only where step two needs step one's output.
- On an open design question, SHOULD dispatch a few Opus delegates from different angles and synthesize.

## Effort, not model tier

- Effort - `low`/`medium`/`high`/`xhigh`/`max`, set in the delegate's `effort` frontmatter - is the lever on latency and cost.
- Unset, a delegate inherits the spawner's effort, so a mechanical Sonnet or Haiku one SHOULD run `low`/`medium`.
- Within Opus: a quick disagreement or small two-option call is `medium`; `high`/`xhigh` only for a real architecture decision, a non-obvious root cause, or synthesis across conflicting sources.
- The `Agent` tool has no `effort` parameter - a delegate runs at what its `subagent_type` pins; `Workflow`'s `agent()` does take `opts.effort`.

## Escalation and waiting

- A delegate stuck on an ambiguity, or needing a preference only the user has, SHOULD escalate through main.
- MUST NOT idle-wait for a background agent or command, `sleep`, or issue a placeholder call - a completion re-invokes you: do other work or end the turn.
- A mid-turn message is silently ignored: MUST wait, or re-verify state yourself. Once idle, `SendMessage` resumes a NAMED delegate - MUST ask it for a missing or truncated section, never re-derive it.
- A resend returns a SUMMARY, since its author thinks it sent the report. After one, MUST read its transcript `.jsonl` under `subagents/`, never ask again, and MUST NOT re-run the work.
