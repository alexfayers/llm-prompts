# Reference

Run `llm-prompts --help` or `llm-prompts <command> --help` for every flag.

## Commands

```bash
llm-prompts install <agent>                    # install rules, workflows and skills
llm-prompts install kiro --agent-config PATH   # also patch a Kiro agent JSON
llm-prompts install <agent> --root DIR         # use DIR as the home directory
llm-prompts update                             # report updates, pull sources, copy ready worktrees into local main, reinstall every installed agent
llm-prompts update --check                     # list available updates without applying them
llm-prompts update --only PATH                 # reinstall only the prompt or pi extension (.ts) built from this edited file (refused where the installed env cannot be proven to match the configured source)
llm-prompts update --verbose                    # also list every file changed
llm-prompts uninstall <agent>                  # remove installed files and config patches
llm-prompts source <agent>                     # show the source file paths for an agent
llm-prompts setup                              # install the tools in config.toml
llm-prompts setup <tool>                       # reinstall the shared environment from scratch
llm-prompts setup --dry-run                    # show the commands without running them
llm-prompts setup --init                       # create the starter config
llm-prompts settings                           # edit config.toml's settings in a terminal, review the changed settings and save them with a backup. Needs the `llm-prompts[tui]` extra
llm-prompts settings --check                   # print config.toml's tools, plugins and settings with their defaults, and exit 1 on errors
llm-prompts benchmark                          # compare two llm-prompts refs by running agents through scenarios
llm-prompts check                              # check prompt sizes and pi extension headers
llm-prompts size-report --base-root DIR        # markdown report of prompt size changes
llm-prompts watch gh-pr|gh-triage|cmd TARGET... --until COND [--all] [--follow]  # wait for a PR, a repo's ready-PR list or a command to match, then exit (0 match, 124 --timeout, 1 error). Several targets: any match ends it, --all waits for every one, --follow prints each match and keeps watching until --timeout or a terminal state (gh-pr: merged or closed). `gh-pr --author USER|@me --repo OWNER/REPO... --follow` also re-lists that author's open PRs each poll and adds new ones
llm-prompts pr N --tool NAME                   # check PR N's prompt sizes in its worktree, review it with pi (claude if pi is not on PATH) and fix and push until the review is CLEAN (at most 5 fix rounds), rebase it onto main, then run `contribute ready` on it
llm-prompts contribute list|sync|update|ready  # keep each worktree branch in sync with local main and its own PR
```

`install` runs `setup` first (installs or upgrades the tools in your config), then writes the files for the agent. `--no-update` skips `setup`. `update` pulls every git-based `[[tools]]` and `[[plugins]]` source, copies each local source's ready worktrees (`contribute sync --ready`) into its local main as `contribute sync --apply` does (nothing is pushed, no PR is opened, no recorded worktree is removed, and the worktree a conflict prints goes once `main` holds its resolution), and reinstalls for each agent you have already installed. A copy whose conflict waits for hand resolution leaves main as it is and still installs. It stops before installing when a pull or copy fails or another `contribute` run holds the record lock.

`contribute` is covered in [CONTRIBUTING.md](../CONTRIBUTING.md).

## What gets installed

- Rules are markdown files the agent always reads, such as coding style or commit conventions. Kiro gets one file per rule, in `~/.kiro/steering/`. Claude Code gets one concatenated `~/.claude/rules/llm-prompts.md`, plus one file per rule scoped with `paths`. Codex, Antigravity, OpenCode and Pi get one concatenated `AGENTS.md`.
- A rule with `paths: <glob list>` frontmatter loads when the agent reads a matching file. Claude Code and Kiro get it as a scoped rule file. Pi adds it on a matching `read`, `grep`, `find`, `edit` or `write` (see [pi.md](pi.md)). Codex, Antigravity and OpenCode always load it.
- A rule or skill with `load_when: env:<NAME>` or `load_when: tool:<command>` loads only when the variable is set or the command is on PATH. `load_when` can also list several conditions, as in `load_when: [<kind>, tool:<command>]`, and all of them must hold. A skill's `<target>_load_when`, such as `pi_load_when: []`, replaces `load_when` for that target. Pi checks a rule's conditions in the session, where `tool:` also matches a pi tool, when the rule has no roles or only `roles: lead`. A pi rule with several conditions has its `env:` and `tool:` conditions decided at install time, and the session checks the one condition left. Every other case is decided at install time. Any condition other than `env:` or `tool:` is listed for pi in `conditional-rules.json` under its own name, for another extension to check, and is not checked on the other agents. A `load_when` list allows only one such condition, and only on a rule with no roles or only `roles: lead`. The install also checks agent sources and pi package entries. A `requires_env` or `requires_command` key is deprecated: the install adds it to the `load_when` list as `env:` or `tool:` and logs a warning with the replacement `load_when` line. Any other `requires_*` key fails the install.
- Workflows are step-by-step procedures loaded on demand. Only Pi gets them, as prompt templates.
- Skills are directories with a `SKILL.md` the agent reads before a specific kind of task. They are symlinked, so source edits show up immediately. A skill with `inject_at_start: true` in its `metadata` frontmatter is injected as a `Startup block` by the cline-hooks `SkillStartupBlocks` plugin at the start of a main session.
- Agents are subagent definitions: markdown files with YAML frontmatter. Files in `shared/agents/` go to Claude Code and Pi, files in `claude-code/agents/` go to Claude Code, with template variables substituted.
- Claude Code permissions: `claude-code/permissions.json` in core and in each overlay lists `allow`, `ask` and `deny` rules. `install` and `update` add the rules missing from `~/.claude/settings.json` and record them in the manifest. A rule you already list, in any of the three lists, is kept as is. A rule you remove is not added again. A rule declared in several lists goes to the strictest one (`deny`, then `ask`, then `allow`). `uninstall` removes only the rules llm-prompts added, and only from the settings files it added them to. A file it cannot clean stays recorded for the next `uninstall`.

Shared files are Jinja2 templates, with variables from each agent's `vars.json`. For example `{{RULE_FILES}}` becomes "steering files" for Kiro and "AGENTS.md" for Codex. Text can vary per agent with `{% if AGENT == "pi" %}`, and `has_command("herdr")` is true where that command is on PATH at install time. In a skill, `{{SKILL_DIR}}` becomes the skill's installed directory. Put each block tag on its own line. A placeholder with no value is left as `{{NAME}}` and reported as unreplaced. A template with invalid syntax is skipped by `install` and fails `check`.

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

A `git+` source installs its highest stable release tag (`vX.Y.Z`), or the default branch tip if it has none. A source that already ends in `@<ref>` is left as it is. A local path checkout moves to its highest stable release tag, or its upstream branch if it has none, with its local commits kept on top. For a new release of either kind, the session-start notice shows the user `update available (v0.32.0 -> v0.33.0)` and, for a GitHub source, a `Changelog:` link. Agents get the CHANGELOG sections in between, or the commit subjects when the CHANGELOG has none.

`setup` and `update` clone each `git+` source without a `ref` or `@<ref>` into `~/.llm-prompts/<name>`, at its highest release tag, and set that entry's `source` to the clone in `config.toml`. They print each clone and each config change. A clone already in that folder is reused with its edits untouched. If the folder holds anything else, or the clone fails, the entry keeps its `git+` source and a warning says why. While any tool's installed copy has edits a reinstall would discard, `setup` and `update` name the edited files and stop before they upgrade or reinstall. `setup --dry-run` prints what it would clone.

`ref` is optional. It makes a `git+` entry follow that branch, tag or commit instead of releases, and a local path follow that branch of its remote:

```toml
[[tools]]
name = "llm-prompts"
source = "git+https://github.com/alexfayers/llm-prompts.git"
ref = "main"
```

### Automatic updates

At session start, when updates are available, llm-prompts runs `llm-prompts update` in the background and logs its start time and output to `auto-update.log` in the llm-prompts data dir. It skips the run, and keeps showing the update notice, while a session holds a configured local checkout or plugin checkout, or that checkout has commits its release or remote lacks or edits (untracked files in a local checkout do not count). It never reloads the session: reload once it finishes. `update`, `install`, `setup`, `contribute sync --apply` and the automatic update share one lock, so a second one refuses to start. The reinstall after a prompt file edit skips while a full update runs, since that update installs the edit. A failed run may leave some tools updated, and the next session start shows why. It does not retry until the installed versions change. Turn it off with:

```toml
[update]
auto = false
```

### Plugins

`[[plugins]]` tracks a git repo of Claude Code plugin skills and agents (a `skills/**/SKILL.md` layout) and installs them for every agent:

```toml
[[plugins]]
name = "mattpocock-skills"
source = "https://github.com/mattpocock/skills.git"
ref = "main"                      # optional: branch, tag or SHA
skills = ["tdd", "code-review"]   # optional: defaults to all
```

`update` fetches and hard-resets each checkout (under `~/.config/llm-prompts/plugin-sources/<name>`) to the upstream tip. A plugin skill never overwrites a built-in or overlay skill of the same name. A plugin `agents/` directory, searched recursively (or the files and directories its `.claude-plugin/plugin.json` `agents` key names, which replace it), installs for Claude Code and pi, and a plugin agent is skipped where a built-in or overlay agent has the same filename or agent name. `commands/`, `hooks/` and MCP/LSP servers are ignored.

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
claude-code/permissions.json  allow, ask and deny rules to add to ~/.claude/settings.json
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

A local tool can set an optional `test` command, run in its checkout (`test = "just test"`). `update` runs it only after it rebases or replays local commits onto the pulled upstream, or after copying ready worktrees changes main. A failure or a timeout after 10 minutes only prints a warning with how to undo the sync. The install still goes ahead.

Run `just` (lint, type-check, test) before opening a PR. See [CONTRIBUTING.md](../CONTRIBUTING.md).
