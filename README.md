# llm-prompts

Cross-agent rules, workflows, and skills for LLM coding assistants.

Supports [Cline](https://github.com/cline/cline), [GitHub Copilot](https://github.com/features/copilot), and [Kiro](https://kiro.dev).

## Quick start

```bash
curl -LsSf https://raw.githubusercontent.com/alexfayers/llm-prompts/main/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) (if needed), installs llm-prompts, and creates a starter config. Then:

```bash
# Edit ~/.config/llm-prompts/config.toml to add your overlay packages, then:
llm-prompts install {agent}    # kiro, cline, copilot, or all
```

When sources are remote (git URLs or PyPI), `install` automatically runs `setup` first to pull the latest versions. Use `--no-update` to skip this.

## Setup config

`llm-prompts setup` reads `~/.config/llm-prompts/config.toml` to install all your tools and overlays in one go.

```toml
[[tools]]
name = "llm-prompts"
source = "git+https://github.com/alexfayers/llm-prompts.git"

[[tools]]
name = "cline-hooks"
source = "git+https://github.com/alexfayers/cline-hooks.git"

[[tools]]
name = "mcp-memory"
source = "git+https://github.com/alexfayers/mcp-memory.git"
standalone = true
overlays_for = ["llm-prompts", "cline-hooks"]
```

Each `[[tools]]` entry has:

| Field | Description |
|---|---|
| `name` | Tool name |
| `source` | Local path (`~/...`), PyPI package name, or `git+` URL |
| `overlays_for` | List of tools this package plugs into as an overlay |
| `standalone` | Set `true` if the tool also needs its own install (e.g. it has a CLI) |

Tools without `overlays_for` are installed as standalone. Overlays are added via `--with-editable` (local) or `--with` (PyPI/git) to their target tools. The installer is auto-detected (`uv` > `pipx` > `pip`).

```bash
llm-prompts setup              # install all tools
llm-prompts setup mcp-memory   # install just one tool
llm-prompts setup --dry-run    # preview commands without running
```

## Overlays

Overlay packages extend llm-prompts with additional rules, workflows, and skills. They register via the `llm_prompts` entry point group:

```toml
# overlay's pyproject.toml
[project.entry-points."llm_prompts"]
my-overlay = "my_package"
```

The entry point value is the Python package name. Prompts are discovered by convention at `<package>/prompts/`:

```
src/my_package/prompts/
  shared/rules/       # rules for all agents
  shared/skills/      # skills for all agents
  cline/rules/        # cline-only rules
  kiro/rules/         # kiro-only rules
```

## CLI

```bash
llm-prompts install <agent>    # install rules/workflows/skills
llm-prompts install <agent> --no-update  # skip auto-update
llm-prompts source <agent>     # show source file paths
llm-prompts setup              # install all configured tools
llm-prompts setup --init       # create starter config
```

## Development

```bash
uv run ruff check --fix && uv run ruff format
```

## Related

- [mcp-memory](https://github.com/alexfayers/mcp-memory) - persistent memory MCP server (overlay for llm-prompts and cline-hooks)
- [cline-hooks](https://github.com/alexfayers/cline-hooks) - lifecycle hooks framework for AI coding assistants
