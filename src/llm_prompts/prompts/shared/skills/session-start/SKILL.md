---
name: session-start
description: Check memory for in-progress tasks and active TODOs at the start of each session. Use at the beginning of every new conversation.
---

# session-start

At the start of every session, before responding to the user's first message, check memory for in-progress work using **compact mode** to minimise token usage:

0. If a `HANDOFF.md` is in the workspace root, stop this checklist and run the `pickup` skill instead - it covers reading, deleting, and resuming the doc, and includes its own memory lookups. Do not run the rest of this checklist first.
1. `read_graph(project="<repo-name>")` for recent entities in the current workspace.
2. Check whether the user's opening message names a specific task, file, feature, or topic. A generic opening (bare greeting, "what's up", "anything to pick up") has none.
   - **Generic:** run `search_all_projects(query="task", projects=["global", "<repo-name>"], expand_groups=True, entityType="task", status=["in-progress", "planned"], max_observation_chars=0)`. `expand_groups=True` resolves group siblings server-side (no separate `get_group_members` call); the `status` list ORs both states. Results come back grouped by project. `read_graph` only returns 10 recent entities from one project and misses other scopes - not a substitute here.
     To scan every project, omit `projects`/`expand_groups` (status list still applies). Reserve this for an explicit "what's outstanding everywhere?" ask.
   - **Specific:** skip this scan - the "Before starting a task" memory ritual already searches entities relevant to the ask, including always-search items (e.g. `user-preferences`), regardless of this check.
3. If the scan ran, present it in this exact structure - one line per task, no narrative prose, ALL results, no truncation. Each line MUST include a short description from the single observation `max_observation_chars=0` returned - a bare task name is not enough. If an entity has no observations, say `<task-name> - (no description recorded)` rather than omitting the line:

   ```
   **<project>**
   - in-progress: <task-name> - <one-line what-it-is> - <one-line status/next-step, or omit if none>
   - planned: <task-name> - <one-line what-it-is>
   ```

   Repeat per project (in-progress before planned within each). Omit the status line if a project has none.
4. If the scan ran and nothing is in progress or planned, proceed normally without mentioning the check.
5. **Check before drafting your first response, not only while working through this list top-to-bottom.** On Claude Code, Cline, and Kiro, the `AutoReinstallPlugin` cline-hooks plugin checks for llm-prompts source updates automatically at session start (`TaskStart` hook) and injects results as session context. On Codex and Copilot, run `llm-prompts update --check` yourself. Whenever this surfaces updates (either path), summarize them in plain language and flag anything that looks like a breaking change, in the same response - do not just mention updates exist and ask. Applies per source package reporting updates, and even when the opening message names a specific unrelated task. Scan the whole block for an update note before responding. If there are no updates, say nothing.
6. Call memory tools (`read_graph`, `search_all_projects`, `search_nodes`, etc.) directly - ordinary tools in your catalog. Do NOT run a tool-discovery step to "find" or "check availability of" memory first (e.g. `list_mcp_resources`, listing servers) - that lists resources, not tools, and an empty result does not mean memory is unavailable. Only if your harness hides tool schemas behind an explicit `ToolSearch`/deferred-tools step (Claude Code), pre-load once with `select:mcp__memory__add_observations,mcp__memory__read_graph,mcp__memory__search_nodes,mcp__memory__create_entities`; otherwise just call the tools.
7. (Optional) If the user's first message asks about outstanding work (e.g. "what's left?", "any todos?"), run the `todos` skill. Skip by default - the memory task summary above already covers in-progress/planned work; this is only for file/code-level TODOs when specifically relevant.
8. If the workspace is a git repo, check for unmerged local branches with `git branch -v --no-merged <main-branch>` (or `git -P log --all --oneline --not --remotes --not <main-branch>` for commits reachable from no branch's remote tracking ref). Memory only records what a session chose to persist - a branch can hold real, tested, unpushed work with no memory entity. Do this once per repo per session. If found and it looks like real work (not throwaway/experiment), mention it alongside the memory-derived tasks - the user decides, but only after being told. A tip commit far behind main is likely stale/superseded rather than actionable - note that distinction.
