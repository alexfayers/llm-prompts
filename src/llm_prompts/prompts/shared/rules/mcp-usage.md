---
roles: lead
---

# MCP Usage

You can and SHOULD use multiple tools in a single call, in parallel.

- Where the tool name is known, MUST NOT list or search tools. Where tools are deferred, MUST load only that tool's schema (select by exact name).
{% if AGENT == "claude-code" %}
- Where several known tools are deferred, MUST load them in one `ToolSearch` call: `select:<name>,<name>`.
{% endif %}
- MUST NOT repeat a call whose arguments and result are already in context, unless the state may have changed since.

When in {{PLAN_MODE}}, ALWAYS use read-only tools.
