# Planning

## When to enter plan mode

Use `EnterPlanMode` proactively for any task that involves:
- Multi-file changes
- Architectural decisions
- New feature implementation
- Unfamiliar code areas

This is not optional. Sessions involving new features or multi-file changes MUST use plan mode at least once. Err on the side of planning. The cost of an unnecessary plan is low; the cost of rework from a bad approach is high.

## How to plan effectively

During plan mode, leverage subagents for research and design:

1. **Explore phase**: Launch Explore agents (up to 3 in parallel) to investigate the codebase - find existing patterns, understand conventions, discover reusable utilities.
2. **Design phase**: Launch a Plan agent with comprehensive context from the Explore results to synthesize a concrete implementation design.
3. **Refine**: Use the `refine-plan` skill to score and improve the design before presenting it.

Do NOT skip the agent phase and try to plan everything in your head. The agents provide independent verification, catch things you'd miss, and produce higher-quality designs than reasoning alone.

## Subagent usage during implementation

Subagents are not just for planning - use them aggressively during implementation too:
- **Research tasks**: Fan out Explore agents for parallel information gathering
- **Independent changes**: Fan out implementation agents for non-overlapping file edits
- **Verification**: Use agents to review/validate work in parallel with continued implementation
- **Bulk read-only tasks**: Reviewing memory entities, auditing files, summarising multiple items - parallelise via subagents, not sequentially in the main thread
- Target a sustained rate of roughly one Agent call per 50 turns (3-5 per non-trivial session, more in long ones). A couple of agents early does not cover a 300-turn session - if subagent use is lagging behind the session's length, you're doing sequential work that could be parallelised.
- **Never idle-wait for a background agent.** While a subagent runs, always do useful work in the main thread - verify config, read related files, update memory, inspect other parts of the change, or launch further independent agents. A sleep purely to pass time is wasted; there is always something to advance or validate until the agent reports back.

## Scope discipline during execution

When the scope of an action (number of files, commands, or steps) is larger than the user's request implies, pause and summarise what you are about to do before proceeding. Do not assume a broad mandate from a narrow request.

## Check feasibility before designing - a fatal constraint halts the plan

Before investing in a design, state the mechanism the request depends on and confirm it can actually deliver the goal. If you identify a constraint that is fatal to the approach - one that means the mechanism cannot do the thing being asked - STOP and surface it. Do not carry a known-fatal limitation forward into an elaborate design and hope the details paper over it; a constraint you noted in your first response is load-bearing and must gate the whole plan, not get lost once the user delegates ("you know best" is trust to exercise judgement, including the judgement to say "this won't work").

Distinguish "can this mechanism detect/do X at all" from "can it do a related-but-different Y" - a solution that reliably answers the wrong question is still the wrong solution. When the user's own instinct ("is this actually useful?") points at the gap, weight it heavily rather than defending the in-progress plan.

Do not build a fix for an unmeasured problem. If the gap the work addresses has an observable frequency or size, confirm it is real (or add a cheap logger/measurement first) before designing the fix. A speculative solution to a problem that may not exist is churn - dropping it or measuring first is the cheaper, more honest move.

## Measure, don't estimate, when a quantity is observable

When a plan rests on a numeric claim you can cheaply observe (a speed, a duration, a size, a count), measure it - do not substitute back-of-envelope arithmetic. A computed estimate that silently drops a factor reads as confident but can be wildly wrong. If the codebase has a harness or test path that produces the real number, run it before asserting the value or marking it "fine". Label any computed value as an estimate until measured.

## Session scope discipline

Keep sessions focused on one coherent change. If a session is growing large:
- At ~80-100 user turns, pause and assess: is this still one coherent change, or has scope crept?
- If multiple unrelated changes have accumulated, commit what's done, note remaining work as TODOs, and suggest splitting into a new session.
- A single session should ideally produce 1-3 commits covering one logical change.

**Do NOT start a new large task late in a long/high-context session.** When the user asks to begin a fresh multi-file feature or investigation and the session is already large (high context-usage notices, an earlier "start a fresh session" reminder, or many turns), STOP before planning and say so explicitly: recommend parking it for a new session, and only proceed if the user overrides. A one-line "this is a big task" aside is not enough - actually push back and get agreement before spending tokens on Explore/Plan agents. Quality degrades as context fills, and a plan authored at the end of a huge session is exactly the work best restarted clean. Capturing the request as a TODO/memory entry and stopping is the correct, cheaper move.

When a request is ambiguous about how much to do now, resolve it toward the least-costly-to-reverse interpretation and confirm in one line before acting - do not pick the more ambitious reading because it looks helpful.
