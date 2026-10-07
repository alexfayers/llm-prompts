---
name: session-end
description: Checklist for wrapping up a session - persist memory, check TODOs, and ensure nothing is lost. Use before marking a task complete or ending a conversation.
---

# session-end

Before you end the session or {{TOOL_COMPLETE}}, work through this checklist:

1. **Persist memory (MANDATORY).** Save everything learned this session - decisions, discoveries, corrections, new preferences - to memory (project and/or global). MUST make at least one memory write call (`create_entities`, `add_observations`, or `set_entity_status`) before completing. If nothing was learned, add an observation to the relevant task/project entity noting what was done.
   - Store only current-state facts, outcomes, and reusable learnings - NOT session logs, implementation play-by-play, or anything duplicating steering rules. On resolving a task, trim its observations to 1-3 (outcome only).
   - Shared agent-team `TaskList` items are not memory - they die with the session. If a `TaskList` is active, run `TaskList` and check every non-`completed` item, including anything explicitly deferred. Each such item MUST get its own memory `task/` entity (status `planned`/`blocked`, with a relation) if it doesn't already have one.
2. **Update task entities.** Set the status of any `task/` entities worked on (`resolved`, `blocked`, etc.) across every project scope touched this session, not just the starting one. On resolving a task, delete verbose implementation observations - keep only the outcome summary.
3. **Reflect on {{RULE_FILES}}.** If the session involved user feedback or corrections, update any {{RULE_FILES}} or skill files needed to prevent the same issues next time. Apply improvements directly.
4. **Review tasks.** Skip if arrived here from the `handoff` skill. Run `search_all_projects(query="task", projects=[...], expand_groups=True, entityType="task", status=["in-progress", "planned"], names_only=True, limit=500)` over each project touched this session plus `global`. MUST list only tasks this session worked on, unblocked or found. MUST run the `todos` skill and show the full list only when the user asks.

   Present as ONE markdown table, not prose or bullets - one row per item, grouped by project, in-progress before planned, then TODOs. Fill "What it is" from the task name, blank where the name says it - `get_entity_with_relations` only on tasks the user picks. Omit projects with nothing:

   ```
   | Project | Status | Task | What it is |
   |---|---|---|---|
   | <project> | in-progress | <task-name> | <what-it-is> - <status/next-step> |
   | <project> | planned | <task-name> | <what-it-is> [- unblocked by this session] [- blocks: <other-task>] |
   | <project> | TODO | <file>:<line> | <text> |
   ```

   Append bracketed tags only when they apply. Render a positive vote_score as star symbols (e.g. ★3) after the task name.

5. **Hand off remaining work (conditional).** If incomplete work remains scoped to this project or directly related - `in-progress` task entities, related `planned` tasks, or any non-`completed` shared `TaskList` item (per step 1) - run the `handoff` skill to write `HANDOFF.md`. Base it on step 4's findings, restricted to the current/related effort - do NOT trigger on the broad cross-project backlog. Skip if no such work remains, or a `HANDOFF.md` was already written this session, or arrived here from `handoff`.
6. **Suggest contributing local changes.** SHOULD run `llm-prompts contribute list`; if it shows anything worth contributing, point the user at the `llm-prompts-contribute` skill - MUST NOT run it yourself. Skip if there's nothing to contribute.

After the checklist, give the user a brief summary of what the session did - a few bullet points of concrete outcomes (what changed, decided, fixed), not a step-by-step replay of the checklist or every tool call. Then tell the user "I have followed the session-end checklist" - and, if produced, that a handoff doc is ready at `HANDOFF.md`.

Uncommitted/unpushed changes are not checked automatically here - use the `check_repos.py` script (`git-usage` skill) to check definitively.
