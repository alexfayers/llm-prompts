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
