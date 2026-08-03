---
name: session-end
description: Checklist for wrapping up a session - persist memory, check TODOs, and ensure nothing is lost. Use before marking a task complete or ending a conversation.
---

# session-end

Before you end the session or {{TOOL_COMPLETE}}, work through this checklist:

1. **Persist memory (MANDATORY).** Review everything learned this session - decisions, discoveries, corrections, new preferences - and ensure it is saved to memory (project and/or global as appropriate). You MUST make at least one memory write call (`create_entities`, `add_observations`, or `set_entity_status`) before completing. If truly nothing was learned, add an observation to the relevant task or project entity noting what was done. Knowledge not persisted is permanently lost.
   - **Quality gate:** Do NOT store session logs, implementation play-by-play, or observations that duplicate steering rules. Store only current-state facts, outcomes, and reusable learnings. If a task is resolved, trim its observations to 1-3 (outcome only).
   - **Shared agent-team TaskList items are not memory - they die with the session.** If an agent-team `TaskList` is active, run `TaskList` now and check every item not `completed`. Anything deferred, out-of-scope-for-this-pass, or otherwise not going to be finished before the session ends MUST get its own memory `task/` entity (status `planned`/`blocked` as appropriate, with a relation per the memory rules) if it doesn't already have one - the shared list itself is scoped to this session/team and is gone once it ends. Do this check even if the item was explicitly deferred on purpose (e.g. "not part of this plan, keep it on the list so it isn't lost") - a deferred item is exactly the case memory needs to hold, since "the list" that was holding it is about to disappear.
2. **Update task entities.** Set the status of any `task/` entities you worked on (`resolved`, `blocked`, etc.) - across every project scope this session touched, not just the one the session started in. When resolving a task, delete verbose implementation observations - keep only the outcome summary.
3. **Check for uncommitted/unpushed changes.** Run the co-located script once per distinct workspace root the session touched (not just the one you started in) - it auto-adds the current `--workspace` AND the prompt/skill source repos (it shells out to `llm-prompts source claude-code` to find those), so there's no need to invoke that separately, but it has no way to discover an unrelated repo you worked in that isn't in either set:

   ```bash
   python3 "<base-dir>/check_repos.py" [--workspace <path>]
   ```

   `--workspace` defaults to the current directory; pass it explicitly once per additional touched repo root. It prints JSON with a `repos` list (each `{path, uncommitted, unpushed, no_upstream}`) and a top-level `clean` flag, and exits non-zero when anything is outstanding (`no_upstream` is informational, not itself a blocker). For each repo with `uncommitted` entries, commit them now. For each repo with `unpushed` entries, surface them to the user and ask how they'd like to submit (push, PR/review, or leave for later). If any repo reports an `error`, investigate before proceeding.
4. **Reflect on {{RULE_FILES}}.** If the session involved user feedback or corrections, consider whether any {{RULE_FILES}} or skill files should be updated to prevent the same issues next time. Apply improvements directly.
5. **Review TODOs (comprehensive).** Skip this step entirely if you arrived here from the `handoff` skill - its own "next task" section already narrows outstanding work to the current effort, and re-running the broad scan here would just re-surface the wider cross-project backlog handoff isn't about. Otherwise, surface ALL outstanding work to the user, scoped to every project this session actually touched (read files in, ran commands in, or discussed) plus `global` - a session that spans multiple repos must review each one, not just the one it started in:
   - For each touched workspace, run the `todos` skill to scan for file- and code-based TODOs (TODO.md files plus TODO/FIXME markers). Fold its findings into the consolidated summary below.
   - Search memory for TODO observations on each touched project's entity and related entities (`search_nodes` with query "TODO")
   - Search memory for planned/in-progress tasks in each touched project and `global`, using `max_observation_chars=0` (keeps just the single highest-voted observation per entity - enough for a one-line "what is this" without pulling full detail)

   Present the result as a flat structured list, not narrative prose - one line per item, grouped by project, in-progress before planned within each group. Every task line MUST include a short description of what the task actually is, taken from the observation `max_observation_chars=0` returned - a bare task name is not enough to act on. If an entity has no observations at all, say so (`<task-name> - (no description recorded)`) rather than omitting it. Omit a project's block entirely if it has nothing to show, and within a shown block omit the `in-progress`/`planned`/`TODO` line for any category that's empty - never print an empty or placeholder line:

   ```
   **<project>**
   - in-progress: <task-name> - <one-line what-it-is> - <one-line status/next-step>
   - planned: <task-name> - <one-line what-it-is> [- unblocked by this session] [- blocks: <other-task>]
   - TODO: <file>:<line> - <text>
   ```

   Append the bracketed tags only when they apply (newly unblocked by this session's work, or a known cross-project dependency) - omit them otherwise.

6. **Hand off remaining work (conditional).** If incomplete work remains that is scoped to this project or directly related to what this session touched - unfinished `TODO.md` items, `in-progress` task entities, `planned` tasks that are part of the current or a directly related effort, or **any non-`completed` shared agent-team TaskList item** (per step 1's check - its work isn't done just because you gave it a memory entity) - run the `handoff` skill to write `HANDOFF.md` so the next session can resume with full context. Base this on the work surfaced in step 5, restricted to the current project / directly related effort - do NOT trigger on the broad cross-project backlog. Skip this step only when no such work remains, or when you already wrote a `HANDOFF.md` this session or arrived here from the `handoff` skill (never re-trigger handoff in those cases).

After completing the checklist, give the user a brief summary of what the session actually did - a few bullet points of the concrete outcomes (what changed, what was decided, what was fixed), not a step-by-step replay of the checklist itself or of every tool call made. Then tell the user "I have followed the session-end checklist" to confirm - and, if you produced one, that a handoff doc is ready at `HANDOFF.md`.
