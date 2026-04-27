---
name: session-start
description: Check memory for in-progress tasks and active TODOs at the start of each session. Use at the beginning of every new conversation.
---

# session-start

At the start of every session, before responding to the user's first message, check memory for in-progress work:

1. `read_graph(project="<repo-name>")` to surface recent entities for the current workspace.
2. **CRITICAL - do NOT skip this step or substitute read_graph results.** Run both of these calls:
   - `search_all_projects(query="task", status="in-progress")`
   - `search_all_projects(query="task", status="planned")`
   These are the **only** authoritative source for the task summary. `read_graph` only returns 10 recent entities from one project and will miss tasks in other scopes.
3. Also check for loose TODOs stored as observations: `search_nodes(project="global", query="TODO")`.
4. Present the task summary grouped by project. Show in-progress tasks first, then planned, then loose TODOs. Include ALL results - do not truncate or summarise away tasks.
5. If nothing is in progress or planned anywhere, proceed normally without mentioning the check.
6. Run `llm-prompts update --check` to see if any tool sources have upstream updates available. If updates are found, mention them to the user.
