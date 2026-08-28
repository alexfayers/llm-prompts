# Planning

## When to enter plan mode

- MUST use `EnterPlanMode` at least once for any task involving multi-file changes, architectural decisions, a new feature, or unfamiliar code.
- SHOULD err on the side of planning - an unnecessary plan costs little, rework costs a lot.
- MUST do the research and design in subagents BEFORE entering plan mode: every main-session tool call inside it re-runs permission checks, producing a wall of redundant prompts.
- Inside plan mode you MUST only present the finished plan, then call `ExitPlanMode`.

## How to plan effectively

Before plan mode, in order: Explore agents (up to 3 in parallel) for existing patterns and reusable utilities; a named Plan agent for a concrete design; the `refine-plan` skill to score it; then `EnterPlanMode` to present. No exploration or iteration after that.

- MUST NOT skip the agent phase and plan in your head.

## Subagent usage during implementation

- SHOULD fan out Explore agents for research, implementation agents for non-overlapping edits, and review agents alongside continued implementation.
- SHOULD push bulk read-only work (auditing files, reviewing memory entities, summarising many items) to subagents.
- SHOULD prefer a named, addressable team over anonymous subagents - a name lets you continue an agent with its context intact. Reserve unnamed subagents for single-turn lookups.
- SHOULD sustain roughly one Agent call per 50 turns. Subagent use lagging the session's length means sequential work that could be parallel.
- MUST NOT idle-wait for a background agent or command - see `delegation.md`.

## Scope discipline during execution

- Where an action's scope (files, commands, steps) is larger than the request implies, MUST pause and summarise what you are about to do first.
- MUST NOT assume a broad mandate from a narrow request.

## Check feasibility before designing

- Before investing in a design, SHOULD state the mechanism the request depends on and confirm it can deliver the goal.
- MUST stop and surface a constraint fatal to the approach rather than carry it forward. "You know best" is trust to exercise judgement, including the judgement to say this will not work.
- SHOULD distinguish "can this mechanism do X at all" from "can it do a related-but-different Y" - reliably answering the wrong question is still wrong; weight the user's instinct over the in-progress plan.
- Before rejecting a mechanism, SHOULD check whether you silently narrowed the goal it was judged against, and re-read the user's literal words on pushback.
- SHOULD NOT build a fix for an unmeasured problem - confirm the gap is real, or measure it cheaply first.
- Where a plan rests on a numeric claim you can cheaply observe, MUST measure it rather than substitute arithmetic, MUST run the codebase's own harness where one produces the real number, and MUST label any computed value an estimate until measured.

## Session scope discipline

- Keep a session to one coherent change, and each logical change to ONE commit - see `git.md`.
- Once unrelated changes have accumulated, SHOULD commit what is done, record the rest as TODOs, and suggest a new session.
- MUST NOT start a new large task late in a long or high-context session. Recommend parking it and proceed only if the user overrides - a one-line aside is not enough, get agreement first.
- This gates the ACT of calling `EnterPlanMode` however trivial the task looks, and MUST happen before any research or plan-writing spend. A context-usage notice stays live until a fresh session starts.
- Once the user has approved continuing past a context-usage notice, that approval stands for the rest of the session - MUST NOT re-ask. Ask again only on a new signal: a more degraded notice tier the user has not seen, or a task the earlier approval would not cover.
- Where the check lands on a clean handoff point - work small, committed and verified, nothing mid-flight - SHOULD run the `handoff` skill or persist plan and TODOs to memory rather than asking the user to pick.
- Where a request is ambiguous about how much to do now, SHOULD resolve it toward the least-costly-to-reverse reading and confirm in one line before acting.

## Multi-phase plans: one lead session per phase

- Each phase is its own unit of work, so SHOULD spin up a fresh lead session per phase - one lead dispatching one implementer per phase still accumulates context across every phase.
- The plan's persisted state (plan-file status markers, a memory entity) MUST be what a fresh lead re-reads to resume, never state held only in the outgoing lead's conversation.
- Before ending a lead session at a phase boundary, MUST confirm the finished phase's implementer reported back and its status is marked done, then stop.
