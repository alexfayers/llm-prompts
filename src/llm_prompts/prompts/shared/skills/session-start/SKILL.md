---
name: session-start
description: Start-up checks. Load only when no start-up blocks were injected.
metadata:
  inject_at_start: true
---

# session-start

Before the first reply, check memory for in-progress work:

{% if AGENT not in ["claude-code", "pi"] %}
0. If `HANDOFF.md` is in the workspace root, run the `pickup` skill instead and stop here.
{% endif %}
0.5. If the workspace root has an operating-rules file (e.g. `RULES.md`), read it in full first.
{% if AGENT not in ["claude-code", "pi"] %}
1. `read_graph(project="<repo-name>")`.
{% endif %}
2. Only if the opening message asks about outstanding work, run `search_all_projects(query="task", projects=["global", "<repo-name>"], expand_groups=True, entityType="task", status=["in-progress", "planned"], names_only=True, limit=500)`. Otherwise skip. To scan every project, omit `projects`/`expand_groups`, only on an explicit "what's outstanding everywhere?" ask.
3. If the scan ran, present ONE table of ALL results, grouped by project, in-progress first. Leave "What it is" blank where the name says it. Call `get_entity_with_relations` only on tasks the user picks:

   ```
   | Project | Status | Task | What it is |
   |---|---|---|---|
   | <project> | in-progress | <task-name> | <what-it-is> - <status/next-step, or omit if none> |
   | <project> | planned | <task-name> | <what-it-is> |
   ```

   Render a positive vote_score as stars (e.g. ★3) after the task name.
4. If the scan found nothing, proceed without mentioning it.
5. If the injected session-start context has a source-update note naming updates, summarize them in plain language and flag breaking changes in the first reply. Otherwise say nothing. Applies even where the opening message names an unrelated task.
6. Call memory tools (`read_graph`, `search_all_projects`, `search_nodes`, etc.) directly{% if AGENT == "pi" %} - they are MCP tools, which pi runs in codemode; call them through it{% else %} - ordinary tools in your catalog{% endif %}. Do NOT run a tool-discovery step first (e.g. `list_mcp_resources`, listing servers).{% if AGENT != "pi" %} Only if your harness hides tool schemas behind an explicit `ToolSearch`/deferred-tools step (Claude Code), pre-load once with `select:mcp__memory__add_observations,mcp__memory__read_graph,mcp__memory__search_nodes,mcp__memory__create_entities,mcp__memory__set_entity_status,mcp__memory__trim_observations_to_outcome,SendMessage,TaskStop`, appending the tool names from the tool-usage startup block if present - every deferred tool the session will reliably need goes in this one call; otherwise just call the tools.{% endif +%}
7. (Optional) If the opening message asks about outstanding work (e.g. "what's left?", "any todos?"), run the `todos` skill for file/code-level TODOs. Skip by default.
8. In a git repo, once per repo per session, check unmerged local branches: `git branch -v --no-merged <main-branch>` (or `git -P log --all --oneline --not --remotes --not <main-branch>`). If one looks like real work (not throwaway), mention it with the memory tasks and let the user decide. A tip far behind main is likely stale - say so.
9. MUST follow `rules/anti-yap.md` in every message this session.
