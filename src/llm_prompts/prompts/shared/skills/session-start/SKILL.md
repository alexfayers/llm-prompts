---
name: session-start
description: Start-up checks, injected at session start.
metadata:
  inject_at_start: true
---

# session-start

Before the first reply:

{% if AGENT not in ["claude-code", "pi"] %}
0. If `HANDOFF.md` is in the workspace root, run the `pickup` skill instead and stop.
{% endif %}
0.5. If the workspace root has an operating-rules file (e.g. `RULES.md`), read it in full first.
{% if AGENT not in ["claude-code", "pi"] %}
1. `read_graph(project="<repo-name>")`.
{% endif %}
2. Only if the opening message asks about outstanding work: run `search_all_projects(query="task", projects=["global", "<repo-name>"], expand_groups=True, entityType="task", status=["in-progress", "planned"], names_only=True, limit=500)`, and the `todos` skill for file/code TODOs. Otherwise skip both. Omit `projects`/`expand_groups` only on an explicit "what's outstanding everywhere?" ask.
3. If step 2 ran, present ONE table of ALL memory task results, grouped by project, in-progress first: `| Project | Status | Task | What it is |`. Leave "What it is" blank where the name says it. Render a positive vote_score as stars (e.g. ★3) after the task name. Call `get_entity_with_relations` only on tasks the user picks. Present file/code TODOs in the `todos` skill's format. If nothing was found, say nothing.
4. If the session-start context has a source-update note naming updates, summarize them in plain language and flag breaking changes in the first reply, even where the opening message names an unrelated task. Otherwise say nothing.
5. Call memory tools directly{% if AGENT == "pi" %} through codemode (they are MCP tools){% else %} (ordinary tools in your catalog){% endif %}. Do NOT run a tool-discovery step first (e.g. `list_mcp_resources`, listing servers).{% if AGENT != "pi" %} Only if your harness hides tool schemas behind `ToolSearch`/deferred tools (Claude Code), pre-load once with `select:SendMessage,TaskStop` plus the tool names from the tool-usage startup block, if present.{% endif +%}
6. In a git repo, once per repo per session, run `git branch -v --no-merged <main-branch>`. If a branch looks like real work (not throwaway), mention it with the memory tasks and let the user decide. A tip far behind main is likely stale - say so.
7. MUST follow `rules/anti-yap.md` in every message this session.
