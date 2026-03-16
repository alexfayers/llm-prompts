---
name: pre-implementation
description: Guidelines for proper implementation and workflow for making code changes. Use once the user confirms that they are ready to start the implementation of a plan.
---

# pre-implementation

Once you being the implementation you MUST follow these rules.

After each change, perform the following steps in order:

1. Review the implementation plan.
1. Begin making changes, following the plan.
    1. If tests do not already cover the changes you have made, create them. All new code MUST be covered if applicable. This applies to both unit and integration test.
1. Run linting/formatting checks to validate your code.
    1. If linting fails, go back to the first step. DO NOT CONTINUE UNLESS LINTING PASSES.
1. Run unit tests to validate all functionality behaves as expected.
    1. If unit tests fail, go back to the first step. DO NOT CONTINUE UNLESS UNIT TESTS PASS.
1. If applicable, update memory with your progress.
1. Suggest updates to any of the aforementioned rules or instructions to include any new information you have gained. Refer to them by their `.md` filename where possible.
6. If there are integration tests available, run those to validate that your changes are functional throughout the whole application chain.
    1. If integration tests fail, go back to the first step. DO NOT CONTINUE UNLESS INTEGRATION TESTS PASS.
7. Validate all of your changes. Go through each change and determine if the functionality is necessary, maintainable, and fall within the scope of the given task.
    1. If you have made changes that do not align with this rule, make adjustments, make TODOs, go back to the first step. DO NOT CONTINUE UNLESS ALL CHANGES ARE FUNCTIONAL.
7. Add and commit your changes with a SHORT and meaningful commit message. Follow the commit style of the repository, never assume formatting.

_NOTE: If tests do not exist in the current workspace, or if the change is the creation/adjustment of a small script, then tests are NOT required._

After each "atomic change", make a commit (and update memory). Always ensure that all tests pass _before_ making any commits.

If you encounter any other issues as you go, or the user asks you to do something that is not in the scope of the original plan, add those tasks or requests as TODOs (in memory, in a comment, or in a `TODO.md` file).

Once all steps in the focus chain have been completed, ALL tests pass, memory is updated (if needed), instruction suggestions have been made, and everything is committed, THEN AND (ONLY THEN!) can you call the `attempt_completion` tool.

**Once ready, use the `new_task` tool to create a new task to keep token usage low**. You are allowed to use `new_task` in PLAN mode for this use case. Make sure to pass all information that you have gathered, or references to it, as well as the established rules.
