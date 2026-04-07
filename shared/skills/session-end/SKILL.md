---
name: session-end
description: Checklist for wrapping up a session - persist memory, check TODOs, and ensure nothing is lost. Use before marking a task complete or ending a conversation.
---

# session-end

Before you end the session or {{TOOL_COMPLETE}}, work through this checklist:

1. **Persist memory.** Review everything learned this session - decisions, discoveries, corrections, new preferences - and ensure it is saved to memory (project and/or global as appropriate). Knowledge not persisted is permanently lost.
2. **Update task entities.** Set the status of any `task/` entities you worked on (`resolved`, `blocked`, etc.).
3. **Check for uncommitted changes.** If there are staged or unstaged changes that should be committed, commit them now.
4. **Reflect on {{RULE_FILES}}.** If the session involved user feedback or corrections, consider whether any {{RULE_FILES}} or skill files should be updated to prevent the same issues next time. Apply improvements directly.
5. **Review TODOs.** Check memory and any `TODO.md` files for outstanding items noted during the session. Surface them to the user.

After completing the checklist, tell the user "I have followed the session-end checklist" to confirm.
