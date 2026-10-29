# Pi

`llm-prompts install pi` writes everything under `$PI_CODING_AGENT_DIR` where that is set, otherwise `~/.pi/agent`.

Pi needs Herdr. Install warns when `herdr` is not on PATH, and pi warns once on session start outside Herdr. Run `herdr integration install pi` to set up the Herdr integration.

## What gets installed

- Rules go into the global `AGENTS.md`, or one file each under `rules/` when `herdr` is on PATH (see [Roles](#roles)).
- [cline-hooks](https://github.com/alexfayers/cline-hooks) is wired in as a pi extension.
- Pi packages listed in `prompts/pi/settings.json`, from core and overlays, are merged into `settings.json` in the agent dir. Pi installs them on startup. Packages you add yourself are left alone. A package can be an object with a `source` and the same `requires_env`, `requires_command` and `requires_absent_command` gates as frontmatter, and is added only where every gate passes.
- `mcp-memory install pi` registers the memory servers in `mcp.json`, which pi's MCP support reads.
- Files under `prompts/pi/seed/` are copied into the agent dir only where absent, so they stay yours to edit. A later overlay replaces the same path. For an existing JSON file, seed keys it has never been offered are added once.

## Roles

With Herdr on PATH, each rule is its own file under `rules/` and the global `AGENTS.md` holds only the rules for the ordinary lead.

- A rule without `roles` frontmatter, or with `roles: all`, is core and reaches the lead and every agent.
- `roles` can list any of `lead`, `coordinator`, `reasoner`, `worker`, `surveyor`, `reviewer` to limit a rule to those roles. Only Pi reads it. An invalid value fails the install.
- Each generated agent definition starts with one `@../rules/<name>.md` line per rule for its role, which Herdsman expands at launch, and sets `inheritGlobalContext: false`.
- A definition's role is its source's `name`. A source with `rules` gets only those rules, one with `omitClaudeMd: true` gets none, and any other name gets every rule.
- Roles are fixed when an agent starts, so changes apply to new agents.

`llm-prompts check` measures the expanded text of each definition and of the lead as `pi_role_prompt_bytes`. The `collection_bytes` total counts the global `AGENTS.md` and the rule files, not the agent definitions or their expansions.

## Seeded config

| File | Effect |
|---|---|
| `extensions/pi-permission-system/config.json` | [pi-permission-system](https://www.npmjs.com/package/@gotgenes/pi-permission-system) policy. Asks before `git push`, forced or `git -c` git commands, `llm-prompts install/setup/update/uninstall/contribute`, `gh pr` and `gh issue` writes, and edits to rule, skill, workflow and agent files. `promptMaxRows` and `promptFieldMaxWidth` of 1000000 start the prompt fully expanded. |
| `zentui.json` | Turns on only the [pi-zentui](https://www.npmjs.com/package/pi-zentui) statusline: directory, git, model, context, tokens and cost. Change it with `/zentui`. |
| `compact-tools.json` | Draws every tool call in the [pi-compact-tools](https://www.npmjs.com/package/pi-compact-tools) compact style. Change it with `/compact-tools`. |
| `net-guard.json` | `mode` and `allow` list for `net-guard`. `net-guard` warns when the file is missing or cannot be parsed. |
| `context-total.json` | `footer` and `intervalSeconds` for `context-total`. |
| `pane-reaper.json` | `enabled`, `graceSeconds` and `intervalSeconds` for `pane-reaper`. |
| `web-search.json` | Disables the `source_check` tool of pi-web-access. |

## Extensions

These live in `src/llm_prompts/prompts/pi/extensions/`. Each file starts with a `//` header naming its commands, config and env vars.

| Extension | Effect |
|---|---|
| `cd` | `/cd <dir>` and a `change_dir` tool move the session (history kept) to another working directory. Both refuse in a managed Herdsman agent, and in a lead that still owns Herdsman agents. |
| `codemode-error-header` | Puts the first error line of a failed `codemode` script in the `Script failed` header. Reading a missing tool name (`tools.foo ? a : b`, `typeof tools.foo`) gives `undefined` instead of throwing, so calling a missing tool fails with a plain `not a function`. Adds a hint for common mistakes and for a script that prints `[object Object]`. |
| `codemode-sleep` | Adds the `sleep` tool: `await tools.sleep({ ms })` in a `codemode` script waits up to 10 minutes. |
| `codemode-wait-until` | Defines `waitUntil(check, { intervalMs, timeoutMs })` at the top of each `codemode` script. |
| `compact-now` | Adds the `compact_now` tool, which compacts the session with a model-written `instructions` summary. |
| `context-total` | `/context-total` reports live context and cost for the session and its running agents. `/context-total footer on\|off` toggles a status-line total. |
| `diff-preview` | Shows the pending change of `edit` and `write` calls, and any other ask with a long preview, as a scrollable preview in the permission box. Uses the diff renderer of pi-compact-tools, or pi's own with a one-time warning where that is missing. Scroll with the mouse wheel (fullscreen mode) or `Alt+Up`/`Alt+Down`. |
| `herdr-permission-blocked` | Shows the Herdr "?" state while a permission prompt waits for the user, including prompts forwarded from subagents. |
| `hide-tools` | Hides rarely used LSP and AST tools from the model, and the task board and process tools in non-interactive sessions. `lsp_diagnostics` stays. |
| `lsp-defaults` | Uses installed `ty` or `ruff` when pyright is absent and no Python server is configured. |
| `mcp-hints` | Helps `codemode` scripts call MCP tools: parses JSON text in results into `structuredContent`, lists tool names once per session, and adds the schema of a tool when a message names it or a script first calls it. Schemas and result shapes are cached in `mcp-hints-cache.json`. |
| `net-guard` | Blocks (`"mode": "block"`) or logs (`"mode": "log"`, to `net-guard.log`) network calls from packages and extensions not in the `allow` list. It wraps `fetch`, the undici dispatcher, `http`/`https` and `net` and attributes calls by stack, so it is best effort and not a security boundary. |
| `pane-reaper` | In a top-level lead running in Herdr, checks on session start and every 60 seconds for agent panes whose owning session is gone. Closes a pane itself only if it is managed, has a Herdsman state file, is idle with a finished task, and is past the 15-minute grace period. Reports any other orphaned pane, and `/pane-reaper close <pane-id>` closes a reported one. Also reports linked worktrees that are safe to remove (clean tree, branch merged into main, unused by any Herdr pane or workspace) but never removes a worktree or branch. `/pane-reaper on\|off` toggles the periodic check. |
| `permission-box` | Shows the permission prompt as one centred box (92% wide, up to 85% of the terminal height) with the `diff-preview` content above the prompt. A dialog it does not recognise is shown unchanged. |
| `popup-defer` | `/popup-defer on\|off\|<ms>` defers dialogs while you type. |
| `prompt-cache-stabilizer` | Keeps the system prompt unchanged between turns so the prompt cache stays valid. |
| `role-switch` | Spawns the listed `role@model:effort` names by switching the delegating agent's model and thinking around `delegate_agent`, so the child inherits them. |
| `tower-do-patch` | Adds the `tower_do_patch` tool, which changes single tasks on the board. |
| `tower-do-slim` | Re-registers `tower_do`, `tower_do_talk` and `tower_do_status` with shorter descriptions. |
