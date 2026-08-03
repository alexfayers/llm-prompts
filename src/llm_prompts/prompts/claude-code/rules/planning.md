# Planning

## When to enter plan mode

Use `EnterPlanMode` proactively for any task that involves:
- Multi-file changes
- Architectural decisions
- New feature implementation
- Unfamiliar code areas

This is not optional. Sessions involving new features or multi-file changes MUST use plan mode at least once. Err on the side of planning. The cost of an unnecessary plan is low; the cost of rework from a bad approach is high.

**Do the research and design work in subagents before entering plan mode, not after.** Every tool call made by the main session while plan mode is active still goes through full permission checks - so exploring and iterating on a design from inside plan mode turns into a wall of redundant approval prompts for tools already allowlisted outside of it. Instead: run the Explore/Design phases below as subagents first (each subagent's own tool calls are its own permission concern, not the main session's), then call `EnterPlanMode` only once the plan is fully formed, so the only thing that happens inside it is presenting the finished plan and calling `ExitPlanMode`. This keeps the plan-mode UI/approval step for the user while eliminating the redundant prompts.

## How to plan effectively

Leverage subagents for research and design, ahead of entering plan mode:

1. **Explore phase**: Launch Explore agents (up to 3 in parallel) to investigate the codebase - find existing patterns, understand conventions, discover reusable utilities.
2. **Design phase**: Launch a named Plan agent with comprehensive context from the Explore results to synthesize a concrete implementation design.
3. **Refine**: Use the `refine-plan` skill to score and improve the design before presenting it.
4. **Enter plan mode to present**: Call `EnterPlanMode`, present the refined plan, and use `ExitPlanMode` to get the user's go-ahead - no exploration or iteration should happen after this point.

Do NOT skip the agent phase and try to plan everything in your head. The agents provide independent verification, catch things you'd miss, and produce higher-quality designs than reasoning alone.

## Subagent usage during implementation

Subagents are not just for planning - use them aggressively during implementation too:
- **Research tasks**: Fan out Explore agents for parallel information gathering
- **Independent changes**: Fan out implementation agents for non-overlapping file edits
- **Verification**: Use agents to review/validate work in parallel with continued implementation
- **Bulk read-only tasks**: Reviewing memory entities, auditing files, summarising multiple items - parallelise via subagents, not sequentially in the main thread
- **Prefer a named, addressable agent team over anonymous fire-and-forget subagents.** Give each agent a `name` so it can be continued via `SendMessage` with its context intact (a follow-up question, a correction, a second pass) instead of re-spawning a fresh agent that has to re-derive everything. Name agents by role (e.g. `auditor-structural`, `impl-api`) so the team is legible. Reserve unnamed one-shot subagents for genuinely single-turn lookups where no follow-up is plausible.
- Target a sustained rate of roughly one Agent call per 50 turns (3-5 per non-trivial session, more in long ones). A couple of agents early does not cover a 300-turn session - if subagent use is lagging behind the session's length, you're doing sequential work that could be parallelised.
- **Never idle-wait for a background agent, and never `sleep` to pass time until one replies.** A background agent's completion, and any teammate message, arrives as an injected notification that re-invokes you - sleeping does not make it come sooner and cannot observe it mid-turn; it only burns wall-clock. If you have nothing left to advance, simply end your turn and let the notification wake you. While a subagent runs, prefer doing useful work in the main thread - verify config, read related files, update memory, inspect other parts of the change, or launch further independent agents - but "do other work" and "end the turn" are the only correct options; a bare `sleep` is neither.

## Scope discipline during execution

When the scope of an action (number of files, commands, or steps) is larger than the user's request implies, pause and summarise what you are about to do before proceeding. Do not assume a broad mandate from a narrow request.

## Check feasibility before designing - a fatal constraint halts the plan

Before investing in a design, state the mechanism the request depends on and confirm it can actually deliver the goal. If you identify a constraint that is fatal to the approach - one that means the mechanism cannot do the thing being asked - STOP and surface it. Do not carry a known-fatal limitation forward into an elaborate design and hope the details paper over it; a constraint you noted in your first response is load-bearing and must gate the whole plan, not get lost once the user delegates ("you know best" is trust to exercise judgement, including the judgement to say "this won't work").

Distinguish "can this mechanism detect/do X at all" from "can it do a related-but-different Y" - a solution that reliably answers the wrong question is still the wrong solution. When the user's own instinct ("is this actually useful?") points at the gap, weight it heavily rather than defending the in-progress plan.

**Before rejecting a mechanism as unfit, check whether you silently narrowed the goal it was being judged against.** Rejecting mechanism Y because it "doesn't do X" is only valid if X is what was actually asked - not a stricter version of X you substituted while reasoning (e.g. hearing "cite sources before the turn is truly done" and silently re-deriving the harder "context must land before the response is drafted at all"). When a user pushes back with "isn't that what we actually want?", re-derive the literal goal from their words before re-checking the mechanism against it - the fix is usually re-reading the ask, not new research.

Do not build a fix for an unmeasured problem. If the gap the work addresses has an observable frequency or size, confirm it is real (or add a cheap logger/measurement first) before designing the fix. A speculative solution to a problem that may not exist is churn - dropping it or measuring first is the cheaper, more honest move.

## Measure, don't estimate, when a quantity is observable

When a plan rests on a numeric claim you can cheaply observe (a speed, a duration, a size, a count), measure it - do not substitute back-of-envelope arithmetic. A computed estimate that silently drops a factor reads as confident but can be wildly wrong. If the codebase has a harness or test path that produces the real number, run it before asserting the value or marking it "fine". Label any computed value as an estimate until measured.

## Session scope discipline

Keep sessions focused on one coherent change. If a session is growing large:
- At ~80-100 user turns, pause and assess: is this still one coherent change, or has scope crept?
- If multiple unrelated changes have accumulated, commit what's done, note remaining work as TODOs, and suggest splitting into a new session.
- A single session should ideally produce 1-3 commits covering one logical change.

**Do NOT start a new large task late in a long/high-context session.** When the user asks to begin a fresh multi-file feature or investigation and the session is already large (high context-usage notices, an earlier "start a fresh session" reminder, or many turns), STOP before planning and say so explicitly: recommend parking it for a new session, and only proceed if the user overrides. A one-line "this is a big task" aside is not enough - actually push back and get agreement before spending tokens on Explore/Plan agents. Quality degrades as context fills, and a plan authored at the end of a huge session is exactly the work best restarted clean. Capturing the request as a TODO/memory entry and stopping is the correct, cheaper move.

**This check is a gate on ENTERING planning, not a step inside it - getting the user's `ExitPlanMode` approval on the plan's content is not the same signal and does not retroactively satisfy it.** A context-usage notice received earlier in the session (even several turns before the multi-file request) is still live until a fresh session starts - don't let intervening turns (an unrelated question, a side investigation) make it feel stale. The moment a request would trigger `EnterPlanMode` per the "When to enter plan mode" section above, check session size FIRST, before doing any Explore/research spend on it: if a context-usage notice has already fired this session, say so and ask before continuing into that research, exploration, or plan-writing at all. Do not treat "the user approved the plan I wrote" as evidence the large-task-late-in-session concern was addressed - approving a plan's content is a different question from whether this was the right session to write it in.

**The gate is on the ACT of calling `EnterPlanMode`, not on your assessment of whether the task inside it is "large."** A task that looks trivial (a quick smoke test, a one-line design question, "just testing X") is not exempt - the moment your hand is about to reach for `EnterPlanMode` and a context-usage notice has already fired this session, stop and ask first, regardless of how small the thing being planned seems. Judging the task small enough to skip the check is the exact rationalization that defeats this rule - the notice already fired once; a second read of it after a live turn should raise your prior toward "still relevant," not lower it because you got busy with something else in between.

**Once the user has explicitly approved continuing past a context-usage notice, that approval stands for the rest of the session - do not re-ask on the next notice or the next `EnterPlanMode` reach.** "Explicitly approved" means the user directly answered a continue-or-stop question with continue (or said something equivalent unprompted, e.g. "yes keep going even past 200k"). Re-asking after that is not extra caution, it is re-litigating a decision already made and it reads as nagging. Only ask again if a *new* signal changes the picture - e.g. context has since grown into the next, more degraded notice tier the user hasn't seen yet (check the actual injected note text/tokens rather than assuming from an earlier one which tier a later notice is - do not label a notice "severe" from memory or pattern-matching; read what it actually says), or the user starts a task large enough in scope that the earlier approval (given for a different, smaller ask) plausibly would not have covered it. Track that the approval was given (a one-line note is enough) so a fresh notice on the same session doesn't look unanswered.

**When you ask and the situation is a clean handoff point, default to just doing the handoff rather than posing it as an open question.** "Ask before continuing" does not mean every check produces a bare yes/no back to the user - if the remaining work is already small/optional, the current work is committed and verified, and nothing is mid-flight, that combination of signals IS the answer: run the `handoff` skill (or persist plan/TODOs to memory) without waiting for the user to pick "start fresh" from a menu. Reserve the literal question for when it's genuinely ambiguous - e.g. real uncommitted work in progress, or a next step big enough that continuing vs. stopping is a real trade-off. Asking "continue or start fresh?" when the fresh-start case is obviously the fit is deferring a call you already have the information to make.

When a request is ambiguous about how much to do now, resolve it toward the least-costly-to-reverse interpretation and confirm in one line before acting - do not pick the more ambitious reading because it looks helpful.

## Multi-phase plans: one lead session per phase

A plan with several sequential phases (e.g. a persisted plan file with per-phase status markers) is itself a form of session-scope discipline applied in advance - each phase is its own coherent unit of work. Carry that through to execution: **spin up a fresh main/lead session for each phase**, rather than running every phase's implementer through one long-lived lead session. One lead session dispatching one implementer per phase still accumulates that lead's own context turn over turn across all phases, which is the same degradation this file already warns about for a single growing session - splitting by phase at the *lead* level, not just the implementer level, is what actually resets it.

For this to work, the plan's persisted state (status markers in the plan file, a memory entity pointing to it) must be the source of truth a fresh lead re-reads to resume - never state kept only in the outgoing lead's conversation. Before ending a lead session at a phase boundary: confirm the just-finished phase's implementer has reported back and its status is marked done in the persisted plan, then stop.
