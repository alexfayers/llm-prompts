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
5. Run `llm-prompts update --check` to see if any tool sources have upstream updates available. If updates are found, mention them to the user.
6. Pre-load commonly used deferred tools in a single `ToolSearch` call to reduce latency later in the session: `select:mcp__memory__add_observations,mcp__memory__read_graph,mcp__memory__search_nodes,mcp__memory__create_entities`.
