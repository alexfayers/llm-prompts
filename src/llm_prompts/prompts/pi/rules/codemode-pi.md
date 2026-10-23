---
roles: all
---

# Codemode - pi-specific

- MUST put independent reads in one codemode script.
- MUST NOT declare a codemode script variable named `tools`.
- Where the tool name is known, MUST NOT search for it. Before its first call, MUST read its arguments with `describeTool("mcp__<server>__<name>")`.
- Where a named tool is not available, MUST report it missing and stop - MUST NOT look for a substitute.
