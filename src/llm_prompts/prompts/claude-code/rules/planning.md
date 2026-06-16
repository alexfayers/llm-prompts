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

## Scope discipline during execution

When the scope of an action (number of files, commands, or steps) is larger than the user's request implies, pause and summarise what you are about to do before proceeding. Do not assume a broad mandate from a narrow request.

## Session scope discipline

Keep sessions focused on one coherent change. If a session is growing large:
- At ~80-100 user turns, pause and assess: is this still one coherent change, or has scope crept?
- If multiple unrelated changes have accumulated, commit what's done, note remaining work as TODOs, and suggest splitting into a new session.
- A single session should ideally produce 1-3 commits covering one logical change.
