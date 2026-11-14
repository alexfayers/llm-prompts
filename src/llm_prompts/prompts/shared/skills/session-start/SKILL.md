---
name: session-start
description: Start-up checks. Load only when no start-up blocks were injected.
metadata:
  inject_at_start: true
---

# session-start

Before the first reply, run this once. Then do each printed step in order:

```bash
python3 "<base-dir>/checklist.py" --agent {{AGENT}} [--outstanding] [--everywhere] [--updates]
```

- `--outstanding`: the opening message asks about outstanding work.
- `--everywhere`: it asks what is outstanding everywhere.
- `--updates`: the injected session-start context has a source-update note naming updates.

If the script prints nothing, reply as normal.

Call memory tools (`read_graph`, `search_all_projects`, `search_nodes`, etc.) directly{% if AGENT == "pi" %} - they are MCP tools, which pi runs in codemode; call them through it{% else %} - ordinary tools in your catalog{% endif %}. Do NOT run a tool-discovery step first (e.g. `list_mcp_resources`, listing servers).{% if AGENT != "pi" %} Only if your harness hides tool schemas behind an explicit `ToolSearch`/deferred-tools step (Claude Code), pre-load once with `select:SendMessage,TaskStop`, appending the tool names from the tool-usage startup block if present - every deferred tool the session will reliably need goes in this one call; otherwise just call the tools.{% endif +%}

MUST follow `rules/anti-yap.md` in every message this session.
