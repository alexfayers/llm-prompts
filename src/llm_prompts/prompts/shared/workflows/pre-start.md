---
description: Workflow to follow after each change - test, lint, commit
copilot_mode: agent
---

After each change, perform the following steps in order:

1. If tests do not exist for your changes, create them.
2. Run tests to validate all functionality behaves as expected.
3. If tests fail, go back to step 1. DO NOT CONTINUE UNLESS TESTS PASS.
4. If applicable, update memory with your progress.
5. Suggest updates to any of the aforementioned rules or instructions to include any new information you have gained. Refer to them by their `.md` filename where possible.
6. Add and commit your changes with a SHORT and meaningful commit message. Don't use a commit body. Extra context is already being stored in your memory.

_NOTE: If tests do not exist in the current workspace, or if the change is the creation/adjustment of a small script, then tests are NOT required._

After each "atomic change", make a commit. Always ensure that all tests pass _before_ making any commits.

If you encounter any other issues as you go, or the user asks you to do something else, add those tasks as TODOs.

Once all steps in the focus chain have been completed, all tests pass, memory is updated, instruction suggestions have been made, and everything is committed, THEN AND (ONLY THEN!) can you {{TOOL_COMPLETE}}.

{{TOOL_WRAP_UP}}
