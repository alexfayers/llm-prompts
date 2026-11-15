# Pi

`llm-prompts install pi` writes everything under `$PI_CODING_AGENT_DIR` where that is set, otherwise `~/.pi/agent`.

Pi needs Herdr. Install warns when `herdr` is not on PATH, and pi warns once on session start outside Herdr. Run `herdr integration install pi` to set up the Herdr integration.

## What gets installed

- Rules go into the global `AGENTS.md`, or one file each under `rules/` when `herdr` is on PATH (see [Roles](#roles)).
- [cline-hooks](https://github.com/alexfayers/cline-hooks) is wired in as a pi extension.
- Pi packages listed in `prompts/pi/settings.json`, from core and overlays, are merged into `settings.json` in the agent dir. Pi installs them on startup. Packages you add yourself are left alone. A package can be an object with a `source` and the same `requires_env`, `requires_command`, `requires_absent_command` and `requires_pi_runtime` gates as frontmatter, and is added only where every gate passes.
- `mcp-memory install pi` registers the memory servers in `mcp.json`, which pi's MCP support reads.
- Files under `prompts/pi/seed/` are copied into the agent dir only where absent, so they stay yours to edit. A later overlay replaces the same path. For an existing JSON file, seed keys it has never been offered are added once.

## Runtime

`runtime` under `[pi]` in `config.toml` picks pi's delegation runtime: `herdsman` (the default, also for a missing, unknown or unusable setting) or `pi-context`.

- Under `herdsman`, install adds the pi-herdsman package, its coordinator profiles and the overrides disabling its bundled agent definitions, and rules use `delegate_agent`, `steer_agent` and `inspect_agent`.
- Under `pi-context`, install adds none of those, installs no agent definitions and removes the ones it installed before, and rules use `fork` and `result_fetch`.
- `prompts/pi/extension-gates.json` maps an extension's name to `requires_*` gates. The `pi-context` extension installs only under the `pi-context` runtime, and `herdsman-guidance-dedupe` and `role-switch` only under `herdsman`.
- `requires_pi_runtime: <runtime>` in a pi package entry or in frontmatter skips it for pi under any other runtime. Templates can branch on `PI_RUNTIME`.
- Run `llm-prompts install pi` after changing it.

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

These live in `src/llm_prompts/prompts/pi/extensions/`. Each file starts with a `//` header naming its commands, config and env vars. A subdirectory holding an `index.ts` is one extension and is installed whole.

| Extension | Effect |
|---|---|
| `cache-warming` | Keeps the prompt cache warm while a tower-do task this session owns is in progress, until 2 hours after the last request. Main session only. |
| `already-seen` | Replaces a `read`, `grep`, `find` or `ls` result with a short receipt when the same call earlier gave identical output that is still in the model's context. Results after a file change, a fold or a fork are sent in full. |
| `cd` | `/cd <dir>` and a `change_dir` tool move the session (history kept) to another working directory. Both refuse in a managed Herdsman agent, and in a lead that still owns Herdsman agents. |
| `checkpoint` | Adds the `checkpoint` tool. `mark` names a point. `rewind` removes the steps since a mark (default: the latest) from the model's context and adds their outcome, as a model-written summary or the raw tool results. User messages stay in place. Later marks inside the removed steps go too. `target` can also name an earlier tool call without a mark: `-N` is the Nth call back and `<tool>#<n>` the nth call of that tool back. Set `CHECKPOINT_SHAPE=result` to put the outcome in the rewind tool result instead of a separate message. For long work, set `PI_CACHE_RETENTION=long` so the cached prompt up to the mark does not expire before the rewind. |
| `checkpoint-nudge` | Adds a line to a tool result each time another `CHECKPOINT_NUDGE_TOKENS` (default 10000) tool-result tokens build up since the last user message, until a `checkpoint` call, suggesting a rewind of a finished detour with a summary before replying. Off in delegates. |
| `codemode-error-header` | Puts the first error line of a failed `codemode` script in the `Script failed` header. Reading a missing tool name (`tools.foo ? a : b`, `typeof tools.foo`) gives `undefined` instead of throwing, so calling a missing tool fails with a plain `not a function`. Adds a hint for common mistakes and for a script that prints `[object Object]`. |
| `codemode-sleep` | Adds the `sleep` tool: `await tools.sleep({ ms })` in a `codemode` script waits up to 10 minutes. |
| `codemode-wait-until` | Defines `waitUntil(check, { intervalMs, timeoutMs })` at the top of each `codemode` script. |
| `compact-now` | Adds the `compact_now` tool, which compacts the session with a model-written `instructions` summary. |
| `context-total` | `/context-total` reports live context and cost for the session and its running agents. `/context-total footer on\|off` toggles a status-line total. |
| `diff-preview` | Shows the pending change of `edit` and `write` calls, and any other ask with a long preview, as a scrollable preview in the permission box. Uses the diff renderer of pi-compact-tools, or pi's own with a one-time warning where that is missing. Scroll with the mouse wheel (fullscreen mode) or `Alt+Up`/`Alt+Down`. |
| `herdr-permission-blocked` | Shows the Herdr "?" state while a permission prompt waits for the user, including prompts forwarded from subagents. |
| `herdsman-guidance-dedupe` | Replaces the pi-herdsman delegation reminder with a short stub before it is saved, and sends only the first one to the model. |
| `hide-tools` | Hides rarely used LSP and AST tools from the model, and the task board and process tools in non-interactive sessions. `lsp_diagnostics` stays. |
| `status-shortcuts` | `/status` shows the git branch, the open board tasks and the pending asks, and `/board` lists the in-progress and blocked tasks. Typing `status`, `board` or `asks` on its own gives the same answer. None of them makes a model call. `/status explain` asks the model to explain the status. Main session only. |
| `lsp-defaults` | Uses installed `ty` or `ruff` when pyright is absent and no Python server is configured. |
| `mcp-hints` | Helps `codemode` scripts call MCP tools: parses JSON text in results into `structuredContent`, lists tool names once per session, and adds the schema of a tool when a message names it or a script first calls it. Schemas and result shapes are cached in `mcp-hints-cache.json`. |
| `net-guard` | Blocks (`"mode": "block"`) or logs (`"mode": "log"`, to `net-guard.log`) network calls from packages and extensions not in the `allow` list. It wraps `fetch`, the undici dispatcher, `http`/`https` and `net` and attributes calls by stack, so it is best effort and not a security boundary. |
| `outcome-codes` | Shows the model only the header, the `OUTCOME <code> ref:<ref>` line, any `ASK:` and `DENIED:` lines and the delegation status of a pi-herdsman agent result that carries a valid code. A `found-it` result also keeps its next line when it is 200 characters or fewer. The UI keeps the full result. A result without a valid code is unchanged. |
| `pane-reaper` | In a top-level lead running in Herdr, checks on session start and every 60 seconds for agent panes whose owning session is gone. Closes a pane itself only if it is managed, has a Herdsman state file, is idle with a finished task, and is past the 15-minute grace period. Reports any other orphaned pane, and `/pane-reaper close <pane-id>` closes a reported one. Also reports linked worktrees that are safe to remove (clean tree, branch merged into main, unused by any Herdr pane or workspace) but never removes a worktree or branch. `/pane-reaper on\|off` toggles the periodic check. |
| `pending-asks` | Adds the `asks` tool and `/asks`. `asks` pins a question that awaits you in a widget above the editor and removes it once answered. `/asks` lists them without a model call. Main session only. |
| `permission-box` | Shows the permission prompt as one centred box (92% wide, up to 85% of the terminal height) with the `diff-preview` content above the prompt. A dialog it does not recognise is shown unchanged. |
| `pi-context` | In a delegated session (`PI_CONTEXT_CHILD` names its handshake file) blocks every tool call the session's role (`reader`, `writer` or `btw`) may not make, MCP and nested `codemode` calls included. A writer's `bash` commands start in its worktree, main-directory paths move to the worktree, and `edit`/`write` outside it are blocked. A bad handshake blocks every call. Adds the `fork` tool, which runs a read-only `reader` delegate on a copy of the session up to the fork call, with the model, thinking level and directory of the session, so the delegate reuses the prompt cache. The call waits for the delegate's reply and returns its outcome line with the cache numbers of the delegate's first request. The full reply is available through `result_fetch`. `role: "writer"` runs a `writer` delegate in a git worktree under `<agent dir>/pi-context/worktrees` on branch `fork/<name>`. When it replies, its commits are rebased onto the branch of the main checkout, tested in the worktree with `PI_CONTEXT_TEST_CMD`, or else the command `pi-context/test-gates.json` detects from the repository's files (`just`, a package.json `test` script, `uv run pytest`, `make test`, `cargo test`, `go test ./...`), fast-forwarded onto the main checkout and the worktree is removed. After the rebase, the fork's `fixup!`, `squash!` and `amend!` commits fold into their targets in the fork's own range. After the fast-forward, a landed fixup whose target is an unpushed commit of main folds into it, when the main checkout is clean and no rebase or merge is in progress. Unpushed means after the upstream, or else after the merge-base with the remote's default branch, and not on any remote. With no remote nothing on main folds, and a pushed target keeps its fixup as a separate commit. A fold that conflicts is aborted and the work lands as it is. A later landing rebases with `--fork-point`, so a worktree made before main was folded still rebases cleanly. `PI_CONTEXT_LAND_FOLD=off` turns folding off. A repository with no test command lands with an `untested` note. A new worktree installs the dependencies offline of each lockfile whose packages the main checkout has installed. One landing runs at a time and nothing is pushed. The same delegate gets a rebase conflict or failing tests back to fix, twice at most. Otherwise the landing escalates in the tool result and keeps the worktree. Only the top-level session can fork. `PI_CONTEXT_KEEP_FORKS=1` keeps the seed and handshake files of finished forks. In the top-level session, `//btw <question>` runs a read-only `btw` delegate on a copy of the session up to its last settled point and stores the answer as a transcript entry that never reaches the model. |
| `popup-defer` | `/popup-defer on\|off\|<ms>` defers dialogs while you type. |
| `prompt-cache-stabilizer` | Keeps the system prompt unchanged between turns so the prompt cache stays valid, and warns when the system prompt or tool list changes without a new system entry. |
| `result-cap` | Cuts a tool result over 6000 characters (`RESULT_CAP_CHARS`) to its first two thirds of the cap, a marker with a ref, and its last third. A result of 20 or more rows (a JSON list, `grep` lines, paths or `git log` lines) becomes a header with the row count and fields plus its first 20 rows instead, and `grep` results add the top 10 file counts. The `result_query` tool answers questions about such a list by `ref`, with `where` (regex per field), `sort`, `fields`, `count_by`, `limit` and `offset`. The `result_fetch` tool reads the full text back by `ref`, by `offset` and `limit` in characters, or by `pattern` (matching lines). Skips `read`, `edit` and `write`, errors, results with `ASK:` or `DENIED:` lines, and calls made by another tool such as `codemode`. |
| `role-switch` | Spawns the listed `role@model:effort` names by switching the delegating agent's model and thinking around `delegate_agent`, so the child inherits them. |
| `reload-now` | Adds the `reload_now` tool. Pi runs `/reload` once the agent settles, then sends a message so the agent continues. `/reload-now` does the same by hand. An aborted run drops the request. A managed Herdsman agent cannot call it. |
| `tower-do-patch` | Adds the `tower_do_patch` tool, which changes single tasks on the board. |
| `tower-do-slim` | Re-registers `tower_do`, `tower_do_talk` and `tower_do_status` with shorter descriptions. |
| `tower-widget` | Hides the tower-do widget above the editor by default. `/tower-widget` toggles it for the session. |
| `usage-ledger` | Appends one JSON line per tool call to `usage-ledger.jsonl` in the agent directory: time, session, agent role, tool, whether another tool made the call, and the path of any `SKILL.md` read. Also loads in child agents. |
| `turn-thinking` | Lowers the thinking level to `low` (`TURN_THINKING_WAKE_LEVEL` sets another) for turns started by a Herdsman agent result or ask, or a pi-context fork result, then restores the earlier level at the next user prompt. A wake-up keeps the level when the last request's context is above 20000 tokens (`TURN_THINKING_MAX_CONTEXT` sets another). A `think:high` in the prompt raises that turn to `high`. A level you set during the wake-up turn is kept. |
