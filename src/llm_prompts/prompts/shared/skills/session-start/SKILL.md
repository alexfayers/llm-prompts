---
name: session-start
description: Check memory for in-progress tasks and active TODOs at the start of each session. Use at the beginning of every new conversation.
---

# session-start

At the start of every session, before responding to the user's first message, check memory for in-progress work using **compact mode** to minimise token usage:

0. **Check for a `HANDOFF.md` in the workspace root first.** If one is present, stop this checklist and run the `pickup` skill instead - it covers reading, deleting, and resuming from the doc, and already includes its own memory lookups for the entities it points to. Do not run the rest of this checklist first "just to be thorough"; `pickup`'s reads supersede it.
1. `read_graph(project="<repo-name>")` to surface recent entities for the current workspace.
2. **CRITICAL - do NOT skip this step or substitute read_graph results.** Run a single scan across `global`, the current repo, and any group siblings, filtered to open tasks:
   - `search_all_projects(query="task", projects=["global", "<repo-name>"], expand_groups=True, entityType="task", status=["in-progress", "planned"], max_observation_chars=0)`
   `expand_groups=True` resolves group siblings server-side (sibling scopes declared as one tooling system), so there's no separate `get_group_members` call, and the `status` list ORs both states in one call. Results come back grouped by project. This is the **only** authoritative source for the task summary. `read_graph` only returns 10 recent entities from one project and will miss tasks in other scopes.
   To scan **every** project instead (not just `global` + current repo + siblings), omit `projects`/`expand_groups` (the `status` list still applies). Reserve this for an explicit user request for the full picture (e.g. "what's outstanding everywhere?") - the narrowed scan above is the default.
3. Treat the task summary as background context, not something to dump on the user by default. Only present it when the user's opening message has no specific ask (e.g. a bare greeting, or "what's up" / "anything to pick up"). If the opening message already states a specific task, silently fold in only what's directly relevant to that task - do not print the full summary.

   When presenting, use this exact structure - one line per task, no narrative prose, include ALL results with no truncation. Every task line MUST include a short description of what the task actually is, taken from the single observation `max_observation_chars=0` returned - a bare task name is not enough to act on. If an entity has no observations at all, say so (`<task-name> - (no description recorded)`) rather than omitting the line:

   ```
   **<project>**
   - in-progress: <task-name> - <one-line what-it-is> - <one-line status/next-step, or omit if none>
   - planned: <task-name> - <one-line what-it-is>
   ```

   Repeat the block per project (in-progress tasks before planned within each). Omit a status line entirely if that project has none for it.
4. If nothing is in progress or planned anywhere, proceed normally without mentioning the check.
5. On Claude Code, Cline, and Kiro, the `AutoReinstallPlugin` cline-hooks plugin checks for llm-prompts source updates automatically at session start (via the `TaskStart` hook) and injects any results as session context - surface those to the user if present; you do not need to run the check yourself. On Codex and Copilot (which have no cline-hooks frontend), run `llm-prompts update --check` yourself and mention any updates to the user.
6. Call the memory tools (`read_graph`, `search_all_projects`, `search_nodes`, etc.) directly - they are ordinary tools in your catalog. Do NOT run any tool-discovery step to "find" or "check availability of" memory first (e.g. `list_mcp_resources`, listing servers): that lists resources, not tools, and an empty result does not mean memory is unavailable. If and only if your harness hides tool schemas behind an explicit `ToolSearch`/deferred-tools step (Claude Code), pre-load them once with `select:mcp__memory__add_observations,mcp__memory__read_graph,mcp__memory__search_nodes,mcp__memory__create_entities`; otherwise there is nothing to pre-load - just call the tools.
7. (Optional) If the user's first message asks about outstanding work (e.g. "what's left?", "any todos?"), run the `todos` skill to scan the current workspace. Skip this by default - the memory task summary above already covers in-progress/planned work; this is only for file/code-level TODOs when specifically relevant.
