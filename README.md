# llm-prompts

Installs one shared set of rules, skills, workflows and agents into several LLM coding assistants: Kiro, Claude Code, Codex, Antigravity, OpenCode and Pi.

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/alexfayers/llm-prompts/main/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) if needed, installs `llm-prompts`, and writes a starter `~/.local/share/llm-prompts/llm-prompts/config/config.toml`.

## Quick start

```bash
llm-prompts install <agent>    # kiro, claude-code, codex, antigravity, opencode, pi, or all
llm-prompts update             # check for and list updates, pull new versions, copy ready worktrees into local main, reinstall
llm-prompts uninstall <agent>  # remove installed files
llm-prompts --help             # all commands and flags
```

## Config

`~/.local/share/llm-prompts/llm-prompts/config/config.toml` lists the tools and plugins that `setup` installs. `llm-prompts setup --init` creates the starter file. [reference.md](docs/reference.md#config) lists how `LLM_PROMPTS_HOME` and `XDG_DATA_HOME` change the folder.

Telemetry is anonymous. Turn it off with `DO_NOT_TRACK=1` or `LLM_PROMPTS_NO_TELEMETRY=1`.

## Docs

- [Reference](docs/reference.md): commands, what gets installed, config, plugins, overlays, Kiro, development.
- [Pi](docs/pi.md): extensions, seeded config and roles.
- [Telemetry](docs/telemetry.md): what is sent.
- [Benchmark](docs/benchmark.md): compare two llm-prompts refs by running agents through scenarios.
- [Contributing](CONTRIBUTING.md)

## Related

- [mcp-memory](https://github.com/alexfayers/mcp-memory): persistent memory MCP server.
- [cline-hooks](https://github.com/alexfayers/cline-hooks): lifecycle hooks for AI coding assistants.
