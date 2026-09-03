# Planning

## When to enter plan mode

- MUST use `EnterPlanMode` at least once for any task involving multi-file changes, architectural decisions, a new feature, or unfamiliar code.
- SHOULD err on the side of planning.
- MUST research and design in subagents BEFORE plan mode - main-session tool calls inside it re-run permission checks.
- Inside plan mode you MUST only present the finished plan, then call `ExitPlanMode`.

## How to plan effectively

Before plan mode, in order: Explore agents, one per independent dimension, for existing patterns and reusable utilities; a named Plan agent for a concrete design; `refine-plan` to score it; then `EnterPlanMode`. No exploration or iteration after that.

- MUST NOT skip the agent phase and plan in your head.
- Where the user declines a design question - answering with a constraint, or rejecting the question - MUST treat that constraint as the decision and settle the rest yourself. MUST NOT re-ask reformulated options; state the call in one line.

## Subagent usage during implementation

- SHOULD fan out Explore agents for research, implementation agents for non-overlapping edits, and review agents alongside continued implementation.
- SHOULD push bulk read-only work (auditing, reviewing memory, summarising many items) to subagents.
- SHOULD reserve a named team for work with follow-up; a one-off command run, lookup or single-turn research question goes to an unnamed subagent - see `agent-teams.md`.
- SHOULD sustain roughly one Agent call per 50 turns - lagging that means sequential work that could be parallel.
- MUST NOT idle-wait for a background agent or command - see `delegation.md`.

## Scope discipline during execution

- Where an action's scope (files, commands, steps) is larger than the request implies, MUST pause and summarise it first.
- MUST NOT assume a broad mandate from a narrow request.

## Check feasibility before designing

- Before investing in a design, SHOULD state the mechanism the request depends on and confirm it can deliver the goal.
- MUST stop and surface a constraint fatal to the approach rather than carry it forward. "You know best" includes the judgement to say this will not work.
- SHOULD distinguish "can this do X" from "can it do a related-but-different Y"; weight the user's instinct over the in-progress plan.
- Before rejecting a mechanism, SHOULD check whether you silently narrowed the goal it was judged against, and re-read the user's literal words on pushback.
- SHOULD NOT build a fix for an unmeasured problem - confirm the gap is real, or measure it cheaply first.
- Where research rejects EVERY option for reaching the goal, MUST treat that as a framing signal, not a finding - each option was vetoed alone while the goal went unevaluated. MUST NOT ship the leftover scope as if it satisfied the ask: say the goal is unmet, then re-ask constructively or return it to the user. Such a blocker is as often a misplaced responsibility as a veto.
- Where a plan rests on a numeric claim you can cheaply observe, MUST measure it rather than substitute arithmetic, MUST run the codebase's own harness where one produces the real number, and MUST label any computed value an estimate until measured.

## Session scope discipline

- Keep a session to one coherent change, and each logical change to ONE commit - see `git.md`.
- Once unrelated changes have accumulated, SHOULD commit what is done, record the rest as TODOs, and suggest a new session.
- MUST NOT start a new large task late in a long or high-context session. Recommend parking it; proceed only if the user overrides - a one-line aside is not enough, get agreement first.
- This gates calling `EnterPlanMode` however trivial the task looks, before any research or plan-writing spend. A context-usage notice stays live until a fresh session starts.
- Once the user has approved continuing past a context-usage notice, that approval stands for the rest of the session - MUST NOT re-ask. Ask again only on a new signal: a more degraded notice tier the user has not seen, or a task the earlier approval would not cover.
- At a clean handoff point - work small, committed, verified, nothing mid-flight - SHOULD run `handoff` or persist plan and TODOs to memory rather than asking the user to pick.
- Where a request is ambiguous about how much to do now, SHOULD resolve it toward the least-costly-to-reverse reading and confirm in one line before acting.

## Multi-phase plans: one lead session per phase

- SHOULD spin up a fresh lead session per phase - one lead dispatching implementers still accumulates context across every phase.
- The plan's persisted state (plan-file status markers, a memory entity) MUST be what a fresh lead re-reads to resume, never state held only in the outgoing lead's conversation.
- Before ending a lead session at a phase boundary, MUST confirm the finished phase's implementer reported back and its status is marked done, then stop.
