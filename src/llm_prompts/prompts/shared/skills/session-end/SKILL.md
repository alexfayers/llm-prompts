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
4. **Review TODOs (comprehensive).** Skip entirely if arrived here from the `handoff` skill - its "next task" section already narrows scope, so re-running the broad scan would just resurface the wider backlog handoff isn't about. Otherwise surface ALL outstanding work, scoped to every project touched this session (read, ran commands in, or discussed) plus `global`:
   - Per touched workspace, run the `todos` skill (TODO.md files plus TODO/FIXME markers) and fold findings in.
   - `search_nodes` with query "TODO" on each touched project's entity and related entities.
   - Search memory for planned/in-progress tasks in each touched project and `global`, using `max_observation_chars=0` (single highest-voted observation per entity).

   Present as a flat structured list, not narrative prose - one line per item, grouped by project, in-progress before planned within each group. Every task line MUST include a short description from the `max_observation_chars=0` observation - a bare task name is not enough. No observations at all: say so (`<task-name> - (no description recorded)`) rather than omitting it. Omit a project's block entirely if empty, and omit any empty category line within a shown block:

   ```
   **<project>**
   - in-progress: <task-name> - <one-line what-it-is> - <one-line status/next-step>
   - planned: <task-name> - <one-line what-it-is> [- unblocked by this session] [- blocks: <other-task>]
   - TODO: <file>:<line> - <text>
   ```

   Append bracketed tags only when they apply.

5. **Hand off remaining work (conditional).** If incomplete work remains scoped to this project or directly related - unfinished `TODO.md` items, `in-progress` task entities, related `planned` tasks, or any non-`completed` shared `TaskList` item (per step 1) - run the `handoff` skill to write `HANDOFF.md`. Base it on step 4's findings, restricted to the current/related effort - do NOT trigger on the broad cross-project backlog. Skip if no such work remains, or a `HANDOFF.md` was already written this session, or arrived here from `handoff`.

After the checklist, give the user a brief summary of what the session did - a few bullet points of concrete outcomes (what changed, decided, fixed), not a step-by-step replay of the checklist or every tool call. Then tell the user "I have followed the session-end checklist" - and, if produced, that a handoff doc is ready at `HANDOFF.md`.

Uncommitted/unpushed changes are not checked automatically here - use the `check_repos.py` script (`git-usage` skill) to check definitively.
