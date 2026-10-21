# llm-prompts

Cross-agent rules, workflows, skills, and agents for LLM coding assistants.

Supports [Cline](https://github.com/cline/cline), [GitHub Copilot](https://github.com/features/copilot), [Kiro](https://kiro.dev), [Claude Code](https://code.claude.com), [Codex](https://openai.com/codex/), and [Pi](https://github.com/badlogic/pi-mono).

## Quick start

```bash
curl -LsSf https://raw.githubusercontent.com/alexfayers/llm-prompts/main/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) (if needed), installs llm-prompts, and creates a starter config. Then:

```bash
# Edit ~/.config/llm-prompts/config.toml to add your overlay packages, then:
llm-prompts install {agent}    # kiro, cline, copilot, claude-code, codex, antigravity, pi, or all
```

The first `install` bootstraps everything: when a setup config exists, `install` automatically runs `setup` first to install/upgrade the configured packages, then installs rules/workflows/skills for the target agent(s). Pass `--no-update` to skip the automatic `setup`.

From then on, keep everything current with:

```bash
llm-prompts update    # pull tool/plugin sources, refresh packages, reinstall for every agent you've set up
```

`update` re-pulls every git-based `[[tools]]` and `[[plugins]]` source, re-runs `setup` if any `[[tools]]` are remote, then reinstalls for each agent already in your manifest (i.e. every agent you've previously run `install` for) - no need to name agents again. Use `llm-prompts update --check` to see what's available without applying it. `llm-prompts update --only PATH` skips the pulls and setup and reinstalls only the prompt built from that file - the auto-reinstall hook runs this after each edit.

## Concepts

### Rules

Rules are markdown files that steer agent behaviour. They are always active during a session - the agent reads them as part of its system prompt. Examples: coding style guidelines, git commit conventions, banned phrasing.

Rules are installed to agent-specific directories (e.g. `~/.kiro/steering/` for Kiro, `~/Documents/Cline/Rules/` for Cline, `~/.claude/rules/` for Claude Code). Codex, Antigravity, and Pi have no rules directory, so all rules are concatenated into a single `AGENTS.md` (e.g. `~/.codex/AGENTS.md`, `~/.pi/agent/AGENTS.md`). For Pi, everything installs under `$PI_CODING_AGENT_DIR` where set, and [cline-hooks](https://github.com/alexfayers/cline-hooks) is wired in as a pi extension. Pi packages (extensions) declared in `prompts/pi/settings.json` - core and overlays alike - are merged into `~/.pi/agent/settings.json`, where pi installs them on startup; pi's built-in MCP support reads `mcp.json`, where `mcp-memory install pi` registers the memory servers. Packages you add yourself are left alone. A package entry can also be an object with a `source` and the same `requires_env`/`requires_command`/`requires_absent_command` gates as frontmatter; it is added only where every gate passes. Files under `prompts/pi/seed/` - core and overlays, a later overlay replacing the same path - are copied into the pi agent directory only where absent, so they stay yours to edit; the default seeds a [pi-permission-system](https://www.npmjs.com/package/@gotgenes/pi-permission-system) policy that asks before `git push`, forced or `git -c` commands, `gh pr`/`gh issue` writes, and edits to rule, skill, workflow and agent files. A seeded `zentui.json` turns on only the [pi-zentui](https://www.npmjs.com/package/pi-zentui) statusline, with a footer of directory, git, model, context, tokens and cost; change it with `/zentui`. A seeded `compact-tools.json` sets [pi-compact-tools](https://www.npmjs.com/package/pi-compact-tools) to draw every tool call, `codemode` and the Herdr tools included, in its compact style; change it with `/compact-tools`. The core `pi/extensions/net-guard.ts` extension blocks and logs network calls made by pi packages and extensions missing from the `allow` list in the seeded `net-guard.json` (`"mode": "log"` only logs to `net-guard.log`). It attributes calls by stack and wraps `fetch`, the undici dispatcher, `http`/`https` and `net`, so it is best effort and not a security boundary. The core `pi/extensions/context-total.ts` extension adds `/context-total`, which reports the live context of the session and its running agents, and `/context-total footer on|off`, which toggles a status-line total kept in the seeded `context-total.json`. The core `pi/extensions/codemode-error-header.ts` extension adds the first error line of a failed `codemode` script to the `Script failed` header, so the collapsed row names the error. It also rewrites each `codemode` script so that reading a missing tool name, such as `tools.foo ? a : b` or `typeof tools.foo`, gives `undefined` instead of throwing. Calling a missing tool then fails with a plain `not a function` error. The core `pi/extensions/compact-now.ts` extension adds the `compact_now` tool, which compacts the session with a model-written `instructions` summary. The core `pi/extensions/codemode-sleep.ts` extension adds the `sleep` tool, which `codemode` scripts call as `await tools.sleep({ ms })` to wait up to 10 minutes between calls. The core `pi/extensions/codemode-wait-until.ts` extension adds `waitUntil(check, { intervalMs, timeoutMs })` to the top of each `codemode` script, which polls `check` with `tools.sleep` until it returns a truthy value or the timeout passes. The core `pi/extensions/cd.ts` extension adds `/cd <dir>` and a `change_dir` tool, which move the session (history kept) to a new working directory. Both refuse in a pi-herdsman managed agent, and in a lead while it still owns pi-herdsman agents. The core `pi/extensions/pane-reaper.ts` extension, active only in a top-level lead running in Herdr (outside Herdr it shows a one-time warning on session start), checks on session start and every 60 seconds for Herdr agent panes whose owning session is no longer in any Herdr pane. It closes a pane on its own only when the pane is managed, has a herdsman state file, is idle with a finished task, and is past a 15-minute grace period, and shows a notice for each pane it closes. It only reports any other orphaned pane, and `/pane-reaper close <pane-id>` closes a reported one. It stays silent when the herdsman state format is not the known version. It also reports a linked feature worktree as safe to remove when the tree is clean, the branch is merged into main, and no Herdr pane or workspace uses it, and it reports each worktree it keeps with the reason. It never removes a worktree or a branch. It checks every git repo. Merged means an ancestor of main, plus a merged pull request found with `gh` only where the `origin` remote is GitHub. With no remote or another host, it runs no `gh`. `/pane-reaper` checks now and `/pane-reaper on|off` toggles the periodic check, kept in the seeded `pane-reaper.json` (`enabled`, `graceSeconds`, `intervalSeconds`). The core `pi/extensions/prompt-cache-stabilizer.ts` extension drops system-prompt section removals that pi makes on agent-triggered runs, which would rewrite the prompt cache. The core `pi/extensions/diff-preview.ts` extension shows the pending change of `edit` and `write` calls, and any other ask with a long preview, in the style of [pi-compact-tools](https://www.npmjs.com/package/pi-compact-tools), drawn by that package's diff renderer from the pi agent directory, with line numbers, syntax colours and tinted change rows. Where the package is missing or its renderer fails, the preview uses pi's own diff renderer and shows a warning once per session. The preview appears inside the permission box, above the prompt, under a titled header, and the prompt shows only the one-line summary. A `bash` command, or the input preview of any other tool, that has more than one line or over 120 characters shows the same way as plain wrapped text titled with the tool name, and the prompt keeps only its first line, clipped to 120 characters. The preview fills what remains of the box height after the prompt rows, and is left out when fewer than three rows remain. Scroll it with the mouse wheel (fullscreen mode) or `Alt+Up`/`Alt+Down`. The `diff-preview` link in the seeded `authorizerChain` always defers the decision, and the preview also covers asks forwarded from subagents. It publishes each preview to a shared slot keyed by request id and removes it when the ask is decided. The seeded `promptMaxRows` and `promptFieldMaxWidth` of 1000000 make the prompt start fully expanded. The core `pi/extensions/permission-box.ts` extension shows the permission prompt as one centred floating box, in the style of the [pi-ask-user](https://www.npmjs.com/package/pi-ask-user) dialog: a rounded accent frame with the prompt title in the top border, 92% wide and up to 85% of the terminal height, with the chat, editor and status row still visible around it. It opens the box as a focused overlay once pi-permission-system announces the prompt. The box holds the preview from `diff-preview.ts` when there is one, then a dim divider, then the prompt. The selected option shows an arrow and bold text, and the key hints use dim keys and `•` separators like the dialog. It works with `popup-defer.ts` in any load order. It recognises the prompt by the `PermissionPromptComponent` class name or a first line starting `Permission Required` (checked against pi-permission-system 40.1.1), and shows any other dialog, or a prompt it cannot box, unchanged. The core `pi/extensions/herdr-permission-blocked.ts` extension shows the Herdr "?" state while a permission prompt waits for the user, including prompts forwarded from subagents, and clears it when the prompt is answered.

Pi requires Herdr. Install warns where `herdr` is not on PATH, and pi warns once on session start outside Herdr. Run `herdr integration install pi` yourself to set up the Herdr integration.

With Herdr on PATH, Pi rules install as one file each under `$PI_CODING_AGENT_DIR/rules/`, and the global `AGENTS.md` holds only the rules for the ordinary lead. A rule without `roles` frontmatter is core and reaches the lead and every agent. A rule's `roles` frontmatter, any of `lead`, `coordinator`, `reasoner`, `worker`, `surveyor`, `reviewer`, limits the rule to those roles. Only Pi reads `roles`, other targets ignore it. An invalid `roles` fails the install. Each generated Pi agent definition starts with one `@../rules/<name>.md` line per rule for its role, which Herdsman expands at launch, and sets `inheritGlobalContext: false`. A definition's role is its source's `name`. A source with `rules` gets only those rules, one with `omitClaudeMd: true` gets none, and any other name gets every rule. Role selection is fixed when an agent starts, so changes apply to new agents. `llm-prompts check` measures the expanded text of each definition and of the lead as `pi_role_prompt_bytes`, under the active collection step's ceiling. The pi `collection_bytes` total counts the global `AGENTS.md` and the rule files, not the agent definitions or their expansions.

### Workflows

Workflows are markdown files that define multi-step procedures the agent can follow. Unlike rules (which are always active), workflows are loaded on demand when the agent needs to perform a specific task. Examples: pre-implementation checklist, confidence scoring, oncall investigation. Workflows are installed for Cline only; every other agent gets rules and skills.

### Skills

Skills are directories containing a `SKILL.md` file that the agent reads before performing a specific action. They provide just-in-time guidance for tasks like git operations, session management, or plan refinement. Skills are installed as symlinks, so edits to the source are picked up immediately.

A skill's `metadata` frontmatter can make the cline-hooks `SkillStartupBlocks` plugin inject its text as a `Startup block` at the fresh start of a main session:

- `inject_at_start: true` injects the skill.

### Agents

Agents are custom subagent definitions - single markdown files with YAML frontmatter (`name`, `description`, `model`, etc.) that define a specialised subagent. Agents in `shared/agents/` are installed for `claude-code` and `pi`; agents in `claude-code/agents/` are installed for `claude-code`, and for `pi` when they ship with this repo. They are installed as files with template variables substituted; for `pi` they are written with pi's frontmatter keys and tool names.

### Templates

Shared rules and workflows use `{{VAR}}` template placeholders that get substituted per agent. For example, `{{RULE_FILES}}` becomes "steering files" for Kiro, ".clinerules files" for Cline, and "AGENTS.md" for Codex. This allows a single source file to work across all agents. Variables are defined in each agent's `vars.json`.

Templates are rendered with Jinja2, so text can vary per agent with block tags such as `{% if AGENT == "pi" %}`, `{% else %}` and `{% endif %}`. Put each block tag on its own line: the line is removed from the output, so no blank line is left behind. `has_command("<name>")` is true where that command is on PATH at install time, e.g. `{% if has_command("herdr") %}`. A placeholder with no value stays in the output as `{{NAME}}` and is reported as unreplaced. A template with invalid syntax is skipped during install and fails `llm-prompts check`.

### Overlays

Overlays are separate packages that add extra rules, workflows, and skills on top of the core llm-prompts content. They are useful for organisation-specific or private rules that you don't want in the public repo.

For example, [mcp-memory](https://github.com/alexfayers/mcp-memory) is an overlay that adds memory-related rules and skills. When installed alongside llm-prompts, its content is merged in during `llm-prompts install`. Overlay content takes priority over core content when filenames collide.

## Setup config

`llm-prompts setup` reads `~/.config/llm-prompts/config.toml` to install all your tools in one go.

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

Each `[[tools]]` entry has:

| Field | Description |
|---|---|
| `name` | Tool name |
| `source` | Local path (`~/...`) or `git+` URL |

All tools install into one shared uv environment owned by the first entry; the other entries are added to it with `--with`. The commands each tool declares under `[project.scripts]` in its own `pyproject.toml` are exposed from that environment. `setup` requires uv.

```bash
llm-prompts setup              # install all tools
llm-prompts setup mcp-memory   # reinstall the shared environment from scratch
llm-prompts setup --dry-run    # preview commands without running
```

`setup` installs or upgrades the tools in `config.toml`. Name a tool to reinstall the whole shared environment from scratch, preview the commands with `--dry-run`, or create the starter config with `--init`.

## Telemetry

Every command sends one anonymous event to PostHog (EU). The first run sends nothing and prints a notice.

- Sent for every command and for the session start check (`startup-check`, with `--cached` when it reuses the last result):
  - the command and the sorted names of its flags (never their values)
  - tool versions before and after, each with:
    - `commit`
    - `local`: installed from a path
    - `dirty`: uncommitted changes in a local git checkout, `false` for remote sources, `null` for a local path that is not a checkout
    - `ahead`: commits beyond `origin/main` in a local git checkout, `null` if not counted or not local
  - agent names
  - overlay count, and the version of each overlay installed from a github.com source
  - outcome, duration, OS and Python version
  - schema version
  - a random install id
- Sent on failure: a second event with the exception type and the function, module and line number of each llm-prompts frame in its traceback.
- Never sent: paths, usernames, hostnames, repo names, names of overlays not installed from github.com, prompt or config contents, error messages.
- Off with `DO_NOT_TRACK=1`, `LLM_PROMPTS_NO_TELEMETRY=1`, `CI`, or `[telemetry]` with `enabled = false` in `config.toml`.
- `LLM_PROMPTS_TELEMETRY_DEBUG=1` prints each event and sends it before the command exits.
- Public totals: https://eu.posthog.com/shared/qdUBSB6XFctcGy5jzZ4TCqeNN3UXcQ

## Plugin sources

`[[plugins]]` tracks raw git repos that ship Claude Code plugin/marketplace skills (a `skills/**/SKILL.md` layout, no Python packaging) and fans their skills out to every agent you've installed, the same way built-in and overlay skills are:

```toml
[[plugins]]
name = "mattpocock-skills"
source = "https://github.com/mattpocock/skills.git"
ref = "main"                      # optional; branch/tag/SHA; defaults to the remote's default branch
skills = ["tdd", "code-review"]   # optional; subset by skill directory name; defaults to all
```

| Field | Description |
|---|---|
| `name` | Plugin name; also its checkout directory under `~/.config/llm-prompts/plugin-sources/` |
| `source` | Plain git URL (no pip/PyPI semantics) |
| `ref` | Optional branch/tag/SHA to pin to |
| `skills` | Optional list of skill names to install; installs every discovered skill if omitted |

`llm-prompts update` refreshes each checkout (`git fetch` + `git reset --hard`, so it always lands on the upstream tip regardless of force-pushes or history rewrites) before reinstalling. A plugin skill never overwrites a built-in or overlay skill of the same name - a collision is skipped with a warning. Currently only skills are supported from external plugins; other components (`commands/`, `agents/`, `hooks/`, MCP/LSP servers) are ignored.

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
  shared/rules/         # rules for all agents
  shared/skills/        # skills for all agents
  cline/rules/          # cline-only rules
  kiro/rules/           # kiro-only rules
  shared/agents/        # subagents for claude-code and pi
  claude-code/agents/   # claude-code-only subagents
  pi/settings.json      # pi packages to add to ~/.pi/agent/settings.json
  pi/extensions/        # pi extension files copied to ~/.pi/agent/extensions/
  pi/seed/              # files copied into the pi agent dir only where absent
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
llm-prompts install <agent> --root DIR         # use DIR as the home directory
llm-prompts update                             # pull tool/plugin sources, reinstall every configured agent
llm-prompts update --check                     # report available updates without applying them
llm-prompts update --only PATH                 # reinstall only the prompt built from this edited file
llm-prompts uninstall <agent>                  # remove installed files and config patches
llm-prompts source <agent>                     # show source file paths
llm-prompts setup                              # install all configured tools
llm-prompts setup <tool>                       # install just one tool
llm-prompts setup --dry-run                    # preview install commands without running
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
```

Local paths are installed as copies of the checkout. Changes to rules, workflows, and skills are picked up immediately by `llm-prompts install`; `llm-prompts update` reinstalls only the checkouts whose files outside `prompts/` changed since the last setup, to pick up Python changes.

```bash
llm-prompts setup              # install all tools
llm-prompts install {agent}    # install rules/workflows/skills
```

### Checks

```bash
just    # lint, type-check, test
```

## Related

- [mcp-memory](https://github.com/alexfayers/mcp-memory) - persistent memory MCP server (overlay for llm-prompts and cline-hooks)
- [cline-hooks](https://github.com/alexfayers/cline-hooks) - lifecycle hooks framework for AI coding assistants
