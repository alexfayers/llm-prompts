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

## Concepts

### Rules

Rules are markdown files that steer agent behaviour. They are always active during a session - the agent reads them as part of its system prompt. Examples: coding style guidelines, git commit conventions, banned phrasing.

Rules are installed to agent-specific directories (e.g. `~/.kiro/steering/` for Kiro, `~/Documents/Cline/Rules/` for Cline).

### Workflows

Workflows are markdown files that define multi-step procedures the agent can follow. Unlike rules (which are always active), workflows are loaded on demand when the agent needs to perform a specific task. Examples: pre-implementation checklist, confidence scoring, oncall investigation.

### Skills

Skills are directories containing a `SKILL.md` file that the agent reads before performing a specific action. They provide just-in-time guidance for tasks like git operations, session management, or plan refinement. Skills are installed as symlinks, so edits to the source are picked up immediately.

### Templates

Shared rules and workflows use `{{VAR}}` template placeholders that get substituted per agent. For example, `{{RULE_FILES}}` becomes "steering files" for Kiro and ".clinerules files" for Cline. This allows a single source file to work across all agents. Variables are defined in each agent's `vars.json`.

### Overlays

Overlays are separate packages that add extra rules, workflows, and skills on top of the core llm-prompts content. They are useful for organisation-specific or private rules that you don't want in the public repo.

For example, [mcp-memory](https://github.com/alexfayers/mcp-memory) is an overlay that adds memory-related rules and skills. When installed alongside llm-prompts, its content is merged in during `llm-prompts install`. Overlay content takes priority over core content when filenames collide.

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

## Creating an overlay

Overlay packages register via the `llm_prompts` entry point group:

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

## Kiro agent setup

After installing rules and skills with `llm-prompts install kiro`, you need a Kiro agent config that references them. If you already have an agent JSON file, the installer can patch it automatically:

```bash
llm-prompts install kiro --agent-config ~/.kiro/agents/my-agent.json
```

This adds `resources` entries for the installed steering files and skills to your agent config. If [cline-hooks](https://github.com/alexfayers/cline-hooks) and [mcp-memory](https://github.com/alexfayers/mcp-memory) are installed (included in the default config), it also injects lifecycle hooks, the memory MCP server, and auto-approval for memory tools. If the entries already exist, they are left unchanged.

To set up a Kiro agent from scratch:

1. Run the bootstrap script (installs uv, llm-prompts, and creates a starter config):

```bash
curl -LsSf https://raw.githubusercontent.com/alexfayers/llm-prompts/main/install.sh | sh
```

2. Install all configured tools and overlays:

```bash
llm-prompts setup
```

3. Create a minimal agent config:

```bash
mkdir -p ~/.kiro/agents
cat > ~/.kiro/agents/my-agent.json << 'EOF'
{
  "name": "my-agent",
  "description": "My agent",
  "tools": ["*"]
}
EOF
```

4. Install rules, skills, and patch the agent config:

```bash
llm-prompts install kiro --agent-config ~/.kiro/agents/my-agent.json
```

3. (Optional) Set up [mcp-memory](https://github.com/alexfayers/mcp-memory) for persistent memory across sessions. Add it as an MCP server in your Kiro MCP config and include the memory rules overlay in your `config.toml`.

```bash
mcp-memory install kiro
```

4. (Optional) Set up [cline-hooks](https://github.com/alexfayers/cline-hooks) for lifecycle hooks (pre/post tool use, session start, etc.). Install hooks into your agent config with:

```bash
cline-hook install kiro ~/.kiro/agents/my-agent.json
```

## CLI

```bash
llm-prompts install <agent>                    # install rules/workflows/skills
llm-prompts install kiro --agent-config PATH   # also patch agent JSON with resources
llm-prompts install <agent> --no-update        # skip auto-update
llm-prompts source <agent>                     # show source file paths
llm-prompts setup                              # install all configured tools
llm-prompts setup --init                       # create starter config
```

## Development

To contribute or edit rules locally, clone the repos and use local paths in your config:

```bash
git clone https://github.com/alexfayers/llm-prompts.git
git clone https://github.com/alexfayers/mcp-memory.git
git clone https://github.com/alexfayers/cline-hooks.git
```

Then update `~/.config/llm-prompts/config.toml` to use local paths:

```toml
[[tools]]
name = "llm-prompts"
source = "~/llm-prompts"

[[tools]]
name = "cline-hooks"
source = "~/cline-hooks"

[[tools]]
name = "mcp-memory"
source = "~/mcp-memory"
standalone = true
overlays_for = ["llm-prompts", "cline-hooks"]
```

Local paths are installed as editable, so changes to rules, workflows, and skills are picked up immediately by `llm-prompts install` without needing to re-run `setup`.

```bash
llm-prompts setup              # install all tools as editable
llm-prompts install {agent}    # install rules/workflows/skills
```

### Linting

```bash
uv run ruff check --fix && uv run ruff format
```

## Related

- [mcp-memory](https://github.com/alexfayers/mcp-memory) - persistent memory MCP server (overlay for llm-prompts and cline-hooks)
- [cline-hooks](https://github.com/alexfayers/cline-hooks) - lifecycle hooks framework for AI coding assistants
