# Kiro agent setup

When installing for Kiro, use `--agent-config` to automatically patch the agent JSON with resources, MCP servers, hooks, and tool approvals:

```bash
llm-prompts install kiro --agent-config ~/.kiro/agents/<name>.json
```

If [mcp-memory](https://github.com/alexfayers/mcp-memory) is installed, this also injects the memory MCP server entry, adds `@memory` to `allowedTools` and `tools`, and sets up the background service if not already running.

If [cline-hooks](https://github.com/alexfayers/cline-hooks) is installed, this also injects lifecycle hook entries into the agent config.
