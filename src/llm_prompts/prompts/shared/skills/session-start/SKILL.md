---
name: session-start
description: Check memory for in-progress tasks and active TODOs at the start of each session. Use at the beginning of every new conversation.
---

# session-start

At the start of every session, before responding to the user's first message, check memory for in-progress work:

1. `read_graph(project="<repo-name>")` to surface recent entities.
2. `search_nodes(project="<repo-name>", query="in-progress task", status="in-progress")` to find unfinished tasks.
3. If in-progress tasks or active TODOs exist, briefly summarise them for the user.
4. If nothing is in progress, proceed normally without mentioning the check.
