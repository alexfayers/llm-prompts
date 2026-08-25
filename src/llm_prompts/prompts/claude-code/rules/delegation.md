# Delegate complex thought to subagents

- MUST delegate complex thought - design, architecture, root-cause investigation, debugging, planning, synthesis - to a named Opus agent rather than working through it inline. Reasoning at length in the main thread is the signal to spawn one.
- SHOULD match the Agent tool's `model` to the work, and SHOULD name every agent so it stays addressable.
  - **Opus** - design, architecture, root-cause investigation, debugging, planning, synthesis.
  - **Sonnet** - parallel mechanical execution: an edit pattern Opus already designed, a bounded search, an already-decided step.
  - **Haiku** - the genuinely trivial: a single lookup, a one-line transform, formatting a known value.
- A known target - a specific local file, symbol, or doc you already know is right - is one trivial lookup: SHOULD give it to Haiku, or read it directly when a spawn costs more. MUST NOT let "fetch a known fact" become "go find out about X".
- MUST NOT reach for Haiku where the task involves real reasoning.

## Delegates never hold the `Agent` tool

- Only the main thread spawns; a delegate holding `Agent` can spawn without limit, leaving no visibility into the tree.
- MUST use only subagent types that withhold `Agent`: `reasoner`/`architect` for Opus judgment, `worker` for mechanical execution, `surveyor` for read-only research. MUST NOT reach for a catch-all type (e.g. `general-purpose`).
- Spawning, task assignment and coordination stay with the main thread. A delegate needing more hands reports back.

## A spawn prompt is a bounded contract, not an open question

Every spawn prompt MUST specify:

- the exact sources to check, in preference order: local checkout, then internal or official docs, then the public web only as a last resort;
- the scope boundary - what the delegate MUST NOT go beyond;
- what to do if those sources do not answer it - report back, never silently widen the search.

This binds design delegates as much as research ones: a goal with no sources and no boundary is an open research mandate wearing a design label. Where a delegate must add a code comment, MUST state the comment policy and MUST NOT draft the comment's prose - point at the project's convention and let each delegate in the fan-out write its own line.

## Parallelise by default

- SHOULD parallelise whenever work decomposes, design and research included; independent threads run as concurrent delegates, not one delegate in sequence.
- Where a design question is genuinely open, SHOULD dispatch a few Opus delegates to design from different angles and synthesize the result.
- SHOULD reach for a serial pipeline only when step two needs step one's output.

## Effort is a second axis, independent of model tier

- Effort - `low`, `medium`, `high`, `xhigh`, `max`, set via the delegate's `effort` frontmatter - picks how much capability a task spends, and is the direct lever on latency and cost.
- A delegate inherits the spawner's effort when its own is unset, so a Sonnet or Haiku mechanical delegate SHOULD run at `low` or `medium`.
- Within Opus too: a quick disagreement or a small two-option call is `medium`. Reserve `high`/`xhigh` for a genuine architecture decision, a non-obvious root cause, or synthesis across conflicting sources. Where effort-pinned variants exist, SHOULD pick the one matching the question.
- The `Agent` tool has no `effort` parameter, so a delegate runs at whatever its `subagent_type` pins or the inherited session effort; `Workflow`'s `agent()` does take `opts.effort` per call.
- More than one or two mechanical shell commands with a known recipe is Haiku work - SHOULD spin up a delegate rather than run them inline.

## Escalation and waiting

- A delegate that cannot resolve a genuine disagreement or ambiguity, or where the decision depends on a preference only the user has, SHOULD send it up through the main thread to the user rather than force a resolution alone.
- MUST NOT idle-wait for a background agent or command, and MUST NOT `sleep` or issue a placeholder call to pass time. Completions arrive as an injected notification that re-invokes you. While a delegate runs, either do other useful work or end the turn.
- A follow-up message to a delegate that is already wrapping up crosses with its final report and is silently ignored. MUST either wait for the report, or re-verify the file or state yourself afterwards.
