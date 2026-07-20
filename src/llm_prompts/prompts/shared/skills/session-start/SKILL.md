---
name: session-start
description: Check memory for in-progress tasks and active TODOs at the start of each session. Use at the beginning of every new conversation.
---

# session-start

At the start of every session, before responding to the user's first message, check memory for in-progress work using **compact mode** to minimise token usage:

1. `read_graph(project="<repo-name>")` to surface recent entities for the current workspace.
2. **CRITICAL - do NOT skip this step or substitute read_graph results.** Run both of these calls with `compact=true`:
   - `search_all_projects(query="task", status="in-progress", compact=true)`
   - `search_all_projects(query="task", status="planned", compact=true)`
   These are the **only** authoritative source for the task summary. `read_graph` only returns 10 recent entities from one project and will miss tasks in other scopes. `compact=true` omits observations to save tokens - you only need entity names and statuses for the summary.
3. Present the task summary grouped by project. Show in-progress tasks first, then planned. Include ALL results - do not truncate or summarise away tasks.
4. If nothing is in progress or planned anywhere, proceed normally without mentioning the check.
5. On Claude Code, Cline, and Kiro, the `AutoReinstallPlugin` cline-hooks plugin checks for llm-prompts source updates automatically at session start (via the `TaskStart` hook) and injects any results as session context - surface those to the user if present; you do not need to run the check yourself. On Codex and Copilot (which have no cline-hooks frontend), run `llm-prompts update --check` yourself and mention any updates to the user.
6. Call the memory tools (`read_graph`, `search_all_projects`, `search_nodes`, etc.) directly - they are ordinary tools in your catalog. Do NOT run any tool-discovery step to "find" or "check availability of" memory first (e.g. `list_mcp_resources`, listing servers): that lists resources, not tools, and an empty result does not mean memory is unavailable. If and only if your harness hides tool schemas behind an explicit `ToolSearch`/deferred-tools step (Claude Code), pre-load them once with `select:mcp__memory__add_observations,mcp__memory__read_graph,mcp__memory__search_nodes,mcp__memory__create_entities`; otherwise there is nothing to pre-load - just call the tools.
7. (Optional) If the user's first message asks about outstanding work (e.g. "what's left?", "any todos?"), run the `todos` skill to scan the current workspace. Skip this by default - the memory task summary above already covers in-progress/planned work; this is only for file/code-level TODOs when specifically relevant.
