---
roles: lead
targets: claude-code, pi
---

# Planning

## When to enter plan mode

{% if AGENT == "pi" %}
- For multi-file changes, architectural decisions, a new feature, or unfamiliar code, MUST save memory, then ask the user for `/plan`.
- SHOULD err on the side of planning.
- MUST research and design in subagents BEFORE plan mode - it blocks every non-builtin tool.
- Inside plan mode you MUST only present the finished plan, then call `plan_mode_complete`.
{% else %}
- MUST use `EnterPlanMode` at least once for multi-file changes, architectural decisions, a new feature, or unfamiliar code.
- SHOULD err on the side of planning.
- MUST research and design in subagents BEFORE plan mode - main-session tool calls inside it re-run permission checks.
- Inside plan mode you MUST only present the finished plan, then call `ExitPlanMode`.
{% endif %}

## How to plan effectively

Before plan mode, in order: Explore agents, one per independent dimension, for existing patterns and reusable utilities; a named Plan agent for a concrete design; `refine-plan` to score it; then {% if AGENT == "pi" %}`/plan`{% else %}`EnterPlanMode`{% endif %}. No exploration or iteration after that.

{% if AGENT == "claude-code" %}
- MUST NOT skip the agent phase and plan in your head.
{% endif %}
- Resuming a plan already made and approved (passed `refine-plan`, already exited plan mode - per a handoff doc, memory task-chain, or the plan file's own status) - MUST go straight to execution, not `refine-plan` or {% if AGENT == "pi" %}`/plan`{% else %}`EnterPlanMode`{% endif %} again, unless the record flags a part still needing research.
- Where the user declines a design question - a constraint, or a rejection - MUST treat it as the decision and settle the rest yourself. MUST NOT re-ask reformulated options; state the call in one line.

## Subagent usage during implementation

- SHOULD fan out Explore agents for research, implementation agents for non-overlapping edits, and review agents alongside continued implementation.
- SHOULD push bulk read-only work (auditing, reviewing memory, summarising many items) to subagents.
- SHOULD sustain roughly one {{TOOL_AGENT}} call per 50 turns.

## Scope discipline during execution

- Where an action's scope (files, commands, steps) is larger than the request implies, MUST pause and summarise it first.
{% if AGENT == "claude-code" %}
- MUST NOT assume a broad mandate from a narrow request.
{% endif %}
- 2+ asks: MUST {% if AGENT == "pi" %}add one `tower_do_patch` task each{% else %}`TaskCreate` one entry each{% endif %} before starting.

## Check feasibility before designing

- Before investing in a design, SHOULD state the mechanism the request depends on and confirm it can deliver the goal.
- MUST surface a constraint fatal to the approach rather than carry it forward.
- SHOULD distinguish "can this do X" from "can it do a related-but-different Y"; favour the user's instinct over the plan.
- Before rejecting a mechanism, SHOULD check whether you narrowed the goal it was judged against, and re-read the user's literal words on pushback.
- SHOULD NOT build a fix for an unmeasured problem - confirm the gap is real, or measure it cheaply first.
- Where research rejects EVERY option, treat that as a framing signal, not a finding. MUST NOT ship the leftover scope as if it satisfied the ask: say the goal is unmet, then re-ask or return it to the user.
- Where a plan rests on a numeric claim you can cheaply observe, MUST measure it rather than compute it, run the codebase's own harness when one gives the real number, and label any computed value an estimate until measured.

## Session scope discipline

- Keep a session to one coherent change.
- Once unrelated changes have accumulated, SHOULD commit what is done, record the rest as TODOs, and suggest a new session.
- MUST NOT start a new large task late in a long or high-context session. Park it; proceed only on the user's explicit override, not a one-line aside.
- This gates {% if AGENT == "pi" %}`/plan`{% else %}calling `EnterPlanMode`{% endif %} however trivial, before any research or plan-writing spend. A context-usage notice stays live until a new session.
- Once the user approves continuing past a context-usage notice, that approval stands for the session - MUST NOT re-ask, except on a new signal: a worse notice tier not yet seen, or a task the approval wouldn't cover.
{% if AGENT == "pi" %}
- Past the context threshold, MUST compact with `compact_now` and an `instructions` summary naming the open tasks, asks and decisions.
- At a clean point - work small, committed, verified, nothing mid-flight - SHOULD run `compact_now` or persist plan and TODOs to memory rather than asking the user to pick.
{% else %}
- At a clean handoff point - work small, committed, verified, nothing mid-flight - SHOULD run `handoff` or persist plan and TODOs to memory rather than asking the user to pick.
{% endif %}
- Where a request is ambiguous about how much to do now, SHOULD resolve it toward the least-costly-to-reverse reading and confirm in one line before acting.

## Multi-phase plans: one lead session per phase

- SHOULD spin up a fresh lead session per phase.
- The plan's persisted state (plan-file status markers, a memory entity) MUST be what a fresh lead re-reads to resume, never state held only in the outgoing lead's conversation.
- Before ending a lead session at a phase boundary, MUST confirm the finished phase's implementer reported back and its status is marked done, then stop.
- In an unattended run, MUST persist memory, and write a fresh `HANDOFF.md` at each phase boundary and before any multi-agent loop (e.g. repeated `refine-plan` passes) - long running sessions may end without warning.
