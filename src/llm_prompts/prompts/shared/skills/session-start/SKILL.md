---
name: session-start
description: Check memory for in-progress tasks and active TODOs at the start of each session. Use at the beginning of every new conversation.
---

# session-start

At the start of every session, before responding to the user's first message, check memory for in-progress work:

1. `read_graph(project="<repo-name>")` to surface recent entities for the current workspace.
2. `list_projects()` to discover all project scopes in memory.
3. For each project returned, run `search_nodes(project=<name>, query="task", status="in-progress")` and `search_nodes(project=<name>, query="task", status="planned")` to find unfinished and planned tasks.
4. If tasks exist in any scope, briefly summarise them grouped by project. Show in-progress tasks first, then planned.
5. If nothing is in progress or planned anywhere, proceed normally without mentioning the check.
6. Run `llm-prompts update --check` to see if any tool sources have upstream updates available. If updates are found, mention them to the user.
