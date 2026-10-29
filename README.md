# llm-prompts

Installs one shared set of rules, skills, workflows and agents into several LLM coding assistants: Kiro, Claude Code, Codex, Antigravity and Pi.

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/alexfayers/llm-prompts/main/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) if needed, installs `llm-prompts`, and writes a starter `~/.config/llm-prompts/config.toml`.

## Quick start

```bash
llm-prompts install <agent>    # kiro, claude-code, codex, antigravity, pi, or all
llm-prompts update             # pull new versions and reinstall
llm-prompts uninstall <agent>  # remove installed files
llm-prompts --help             # all commands and flags
```

## Config

`~/.config/llm-prompts/config.toml` lists the tools and plugins that `setup` installs. `llm-prompts setup --init` creates the starter file.

Telemetry is anonymous. Turn it off with `DO_NOT_TRACK=1` or `LLM_PROMPTS_NO_TELEMETRY=1`.

## Docs

- [Reference](docs/reference.md): commands, what gets installed, config, plugins, overlays, Kiro, development.
- [Pi](docs/pi.md): extensions, seeded config and roles.
- [Telemetry](docs/telemetry.md): what is sent.
- [Contributing](CONTRIBUTING.md)

## Related

- [mcp-memory](https://github.com/alexfayers/mcp-memory): persistent memory MCP server.
- [cline-hooks](https://github.com/alexfayers/cline-hooks): lifecycle hooks for AI coding assistants.
