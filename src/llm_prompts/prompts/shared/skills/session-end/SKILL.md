---
name: session-end
description: Checklist for wrapping up a session - persist memory, check TODOs, and ensure nothing is lost. Use before marking a task complete or ending a conversation.
---

# session-end

Before you end the session or {{TOOL_COMPLETE}}, work through this checklist:

1. **Persist memory (MANDATORY).** Review everything learned this session - decisions, discoveries, corrections, new preferences - and ensure it is saved to memory (project and/or global as appropriate). You MUST make at least one memory write call (`create_entities`, `add_observations`, or `set_entity_status`) before completing. If truly nothing was learned, add an observation to the relevant task or project entity noting what was done. Knowledge not persisted is permanently lost.
   - **Quality gate:** Do NOT store session logs, implementation play-by-play, or observations that duplicate steering rules. Store only current-state facts, outcomes, and reusable learnings. If a task is resolved, trim its observations to 1-3 (outcome only).
2. **Update task entities.** Set the status of any `task/` entities you worked on (`resolved`, `blocked`, etc.). When resolving a task, delete verbose implementation observations - keep only the outcome summary.
3. **Check for uncommitted/unpushed changes.** Check the current workspace AND prompt/skill source repos (run `llm-prompts source claude-code` to find them) for:
   - Uncommitted changes - commit them now
   - Unpushed commits - surface them to the user and ask how they'd like to submit (push, PR/review, or leave for later)
4. **Reflect on {{RULE_FILES}}.** If the session involved user feedback or corrections, consider whether any {{RULE_FILES}} or skill files should be updated to prevent the same issues next time. Apply improvements directly.
5. **Review TODOs (comprehensive).** Surface ALL outstanding work to the user:
   - Read all `TODO.md` files in the workspace (use `find` to locate them)
   - Search memory for TODO observations on the current project entity and related entities (`search_nodes` with query "TODO")
   - Search memory for planned/in-progress tasks in the current project and other projects
   - Mention any that are unblocked, overdue, or have cross-project dependencies on what was just completed
   - Present as a consolidated, prioritised list - group by project, highlight anything newly unblocked by this session's work

After completing the checklist, tell the user "I have followed the session-end checklist" to confirm.
