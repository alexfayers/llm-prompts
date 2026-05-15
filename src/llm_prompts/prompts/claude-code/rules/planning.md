# Planning

## When to enter plan mode

Use `EnterPlanMode` proactively for any task that involves:
- Multi-file changes
- Architectural decisions
- New feature implementation
- Unfamiliar code areas

Err on the side of planning. The cost of an unnecessary plan is low; the cost of rework from a bad approach is high.

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
- Target: 3-5 Agent calls per session for any non-trivial task. If you're past 50 turns without having used an Agent, you're likely doing sequential work that could be parallelised.

## Session scope discipline

Keep sessions focused on one coherent change. If a session is growing large:
- At ~80-100 user turns, pause and assess: is this still one coherent change, or has scope crept?
- If multiple unrelated changes have accumulated, commit what's done, note remaining work as TODOs, and suggest splitting into a new session.
- A single session should ideally produce 1-3 commits covering one logical change.
