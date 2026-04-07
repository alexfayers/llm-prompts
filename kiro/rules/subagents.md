# Subagents

Kiro supports spawning parallel AI agents as a DAG pipeline via the `subagent` tool.

## When to use

- Parallel research across multiple topics or codebases
- Independent changes across unrelated modules or files
- Research -> Implement -> Review pipelines where stages have clear boundaries

## When NOT to use

- Simple sequential work that fits in one context
- Tasks requiring tight coordination between steps (e.g. changes that depend on each other's output)
- Small tasks - the overhead of spinning up agents isn't worth it

## Structuring the DAG

- Each stage should be a single, focused task - not a multi-step plan
- Only add `depends_on` for real data dependencies, not just ordering preference
- Use `{task}` in `prompt_template` to reference the overall task description
- Stages without `depends_on` run in parallel automatically

## Memory

- Subagents share the same memory database - they can read and write to the same project
- Instruct subagents to persist findings to memory so downstream stages can pick them up
- Include memory rules in the `prompt_template` so subagents follow the same conventions

## Role selection

- `fayers-default` for general-purpose work with memory access
- `kiro_planner` for breaking down complex problems into plans
- `amzn-builder` for Amazon-specific build and code generation tasks
