---
name: pre-implementation
description: Implementation workflow for code changes. Use once the user confirms they are ready to start implementing a plan.
---

# pre-implementation

Once you being the implementation you MUST follow these rules.

Before you or a delegate writes code, MUST record the plan in memory. Only main writes memory - delegates report decisions and why, and main records them. Find the `feature/` it belongs to, else create one: only project-specific gotchas and decisions with why, never how the code does it. Create one small atomic `task/` per planned step, each `implements` its `feature/` (status `planned`, `in-progress` when started, then its decision and `resolved` when done).

After each change, perform the following steps in order:

1. Review the implementation plan.
1. Begin making changes, following the plan.
1. Run linting/formatting checks to validate your code.
    1. If linting fails, go back to the first step. DO NOT CONTINUE UNLESS LINTING PASSES.
1. Run unit tests to validate all functionality behaves as expected.
    1. If unit tests fail, go back to the first step. DO NOT CONTINUE UNLESS UNIT TESTS PASS.
1. Suggest updates to any of the aforementioned rules or instructions to include any new information you have gained. Refer to them by their `.md` filename where possible.
6. If there are integration tests available, run those to validate that your changes are functional throughout the whole application chain.
    1. If integration tests fail, go back to the first step. DO NOT CONTINUE UNLESS INTEGRATION TESTS PASS.
7. Validate all of your changes. Go through each change and determine if the functionality is necessary, maintainable, and fall within the scope of the given task.
    1. If you have made changes that do not align with this rule, make adjustments, make TODOs, go back to the first step. DO NOT CONTINUE UNLESS ALL CHANGES ARE FUNCTIONAL.
7. Add and commit your changes with a SHORT and meaningful commit message. Follow the commit style of the repository, never assume formatting.
8. If the change affects a running service (e.g. mcp-memory, an MCP server, a daemon), reload it using the project's standard command (e.g. `llm-prompts update`) and smoke test the change live. Never manually restart services when a managed command exists.
9. Resolve the step's `task/` with any decision (why). Add an outcome line only for what git can't show: where it landed (PR/CR number, merged, deployed), what is unverified, a surprise. Each open follow-up becomes its own `planned` `task/`.

_NOTE: If tests do not exist in the current workspace, or if the change is the creation/adjustment of a small script, then tests are NOT required._

After each "atomic change", make a commit (and resolve its `task/`). Always ensure that all tests pass _before_ making any commits.

If you encounter any other issues as you go, or the user asks you to do something that is not in the scope of the original plan, add those tasks or requests as TODOs (in memory as `task/` entities implementing their `feature/`, or in a `TODO.md` file).

Once all steps in the focus chain have been completed, ALL tests pass, memory is updated (if needed), instruction suggestions have been made, and everything is committed, THEN AND (ONLY THEN!) can you {{TOOL_COMPLETE}}.

{{TOOL_WRAP_UP}}
