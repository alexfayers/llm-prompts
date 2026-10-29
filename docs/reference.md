# Reference

Run `llm-prompts --help` or `llm-prompts <command> --help` for every flag.

## Commands

```bash
llm-prompts install <agent>                    # install rules, workflows and skills
llm-prompts install kiro --agent-config PATH   # also patch a Kiro agent JSON
llm-prompts install <agent> --root DIR         # use DIR as the home directory
llm-prompts update                             # pull sources, reinstall every installed agent
llm-prompts update --check                     # list available updates without applying them
llm-prompts update --only PATH                 # reinstall only the prompt built from this edited file
llm-prompts uninstall <agent>                  # remove installed files and config patches
llm-prompts source <agent>                     # show the source file paths for an agent
llm-prompts setup                              # install the tools in config.toml
llm-prompts setup <tool>                       # reinstall the shared environment from scratch
llm-prompts setup --dry-run                    # show the commands without running them
llm-prompts setup --init                       # create the starter config
llm-prompts check                              # check prompt sizes and pi extension headers
llm-prompts size-report --base-root DIR        # markdown report of prompt size changes
llm-prompts contribute list|sync|update        # turn commits on local main into PR branches
```

`install` runs `setup` first (installs or upgrades the tools in your config), then writes the files for the agent. `--no-update` skips `setup`. `update` pulls every git-based `[[tools]]` and `[[plugins]]` source and reinstalls for each agent you have already installed.

`contribute` is covered in [CONTRIBUTING.md](../CONTRIBUTING.md).

## What gets installed

- Rules are markdown files the agent always reads, such as coding style or commit conventions. Kiro and Claude Code get one file per rule, in `~/.kiro/steering/` and `~/.claude/rules/`. Codex, Antigravity and Pi get one concatenated `AGENTS.md`.
- Workflows are step-by-step procedures loaded on demand. Only Pi gets them, as prompt templates.
- Skills are directories with a `SKILL.md` the agent reads before a specific kind of task. They are symlinked, so source edits show up immediately. A skill with `inject_at_start: true` in its `metadata` frontmatter is injected as a `Startup block` by the cline-hooks `SkillStartupBlocks` plugin at the start of a main session.
- Agents are subagent definitions: markdown files with YAML frontmatter. Files in `shared/agents/` go to Claude Code and Pi, files in `claude-code/agents/` go to Claude Code, with template variables substituted.

Shared files are Jinja2 templates, with variables from each agent's `vars.json`. For example `{{RULE_FILES}}` becomes "steering files" for Kiro and "AGENTS.md" for Codex. Text can vary per agent with `{% if AGENT == "pi" %}`, and `has_command("herdr")` is true where that command is on PATH at install time. Put each block tag on its own line. A placeholder with no value is left as `{{NAME}}` and reported as unreplaced. A template with invalid syntax is skipped by `install` and fails `check`.

Pi also gets extensions, seeded config and per-role rules. See [pi.md](pi.md).

## Config

`~/.config/llm-prompts/config.toml` lists the tools `setup` installs:

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
```

`source` is a `git+` URL or a local path (`~/...`). All tools go into one uv environment owned by the first entry, and the commands each tool declares under `[project.scripts]` are exposed from it.

### Plugins

`[[plugins]]` tracks a git repo of Claude Code plugin skills (a `skills/**/SKILL.md` layout) and installs them for every agent:

```toml
[[plugins]]
name = "mattpocock-skills"
source = "https://github.com/mattpocock/skills.git"
ref = "main"                      # optional: branch, tag or SHA
skills = ["tdd", "code-review"]   # optional: defaults to all
```

`update` fetches and hard-resets each checkout (under `~/.config/llm-prompts/plugin-sources/<name>`) to the upstream tip. A plugin skill never overwrites a built-in or overlay skill of the same name. Only skills are used. `commands/`, `agents/`, `hooks/` and MCP/LSP servers are ignored.

## Overlays

An overlay is a separate package that adds rules, skills and agents on top of the core set. [mcp-memory](https://github.com/alexfayers/mcp-memory) is one. Overlays merge with core like this:

- Rules and workflows: the overlay file replaces the core file.
- Skills: overlay files are added into the core skill directory, and a file at the same relative path overrides core's.
- Agents: frontmatter is merged, `tools` are appended without duplicates, and a non-blank overlay body replaces the core body.
- `pi/seed` JSON: deep merged over core. Other seed files are replaced.

To write one, register the package under the `llm_prompts` entry point group:

```toml
# overlay's pyproject.toml
[project.entry-points."llm_prompts"]
my-overlay = "my_package"
```

Prompts are found at `<package>/prompts/`:

```
shared/rules/         rules for all agents
shared/skills/        skills for all agents
shared/agents/        subagents for claude-code and pi
kiro/rules/           kiro-only rules
claude-code/agents/   claude-code-only subagents
pi/settings.json      pi packages to add to ~/.pi/agent/settings.json
pi/extensions/        pi extensions, copied to ~/.pi/agent/extensions/
pi/seed/              files copied into the pi agent dir only where absent
```

## Kiro

Kiro needs an agent config that points at the installed files. To patch an existing one:

```bash
llm-prompts install kiro --agent-config ~/.kiro/agents/my-agent.json
```

This adds `resources` entries for the steering files and skills. With cline-hooks and mcp-memory installed it also adds the lifecycle hooks, the memory MCP server and auto-approval for the memory tools. Entries already there are left alone.

To start from scratch, create `~/.kiro/agents/my-agent.json` with `{"name": "my-agent", "description": "My agent", "tools": ["*"]}`, then run the command above.

## Development

Clone the repos and point `config.toml` at the checkouts:

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
```

Local paths are installed as copies. `llm-prompts install <agent>` picks up changes to rules, workflows and skills right away. `llm-prompts update` reinstalls a checkout only when files outside `prompts/` changed since the last setup.

Run `just` (lint, type-check, test) before opening a PR. See [CONTRIBUTING.md](../CONTRIBUTING.md).
