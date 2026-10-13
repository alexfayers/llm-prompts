---
name: pi-help
description: Walk a new user through what is installed in pi and answer questions about it. Use when the user asks what is set up, how pi works here, or what a command, extension or agent does.
---

# pi-help

Guided tour of this pi setup. Plain words.

## Discover

- MUST read before offering topics:
  - Pi agent dir: `settings.json` `packages`, and the `extensions` and `agents` dirs.
  - The commands `/help` lists.
  - Each installed package's README (`npm/node_modules/<package>` in the pi agent dir, or the source dir of a git or local package).
- MUST build topics from what you found plus the static topics below. MUST NOT list what is not installed.
- MUST explain each item from its README or source, not memory.

## How to run

- MUST go one topic at a time: 2-4 short sentences, then ask what next.
- MUST NOT dump all topics. Offer the list; the user picks.
- MUST answer a question first, then offer to go on.
- MUST name a command only after finding it in `/help` or a README.

## Static topics

Added by llm-prompts, no README. MUST verify each against installed files first.

- **Lead and agents**
  - Your session is the lead and hands work to background agents. pi needs Herdr: outside it, pi and installs warn.
  - Roles: `coordinator` (splits plans into tasks), `worker` (mechanical edits), `surveyor` (read-only research), `reasoner` (design, root cause), `reviewer` (read-only review), `Explore` (quick search).
  - Names are `<kind>-<model>-<effort>`. MUST check `/agents` or installed definitions, MUST NOT state model names from memory.
- **`/reload`**
  - After editing extensions, packages, settings, agents, `AGENTS.md`.
- **Handoff**
  - A handoff starts a new session whose first prompt line is `HANDOFF-ACK <pane-id>`. The old tab stays open until the new session replies with it.
  - Agents MUST NOT run `herdr agent prompt` on a pane the user may be typing in: it presses Enter and wipes the draft.
- **net-guard**
  - Blocks and logs network calls from extensions not in `net-guard.json` `allow`. `"mode": "log"` only logs (`net-guard.log`). Not a security boundary.
- **prompt-cache-stabilizer**
  - Keeps the system prompt stable so the 5-minute cache holds. `cacheWarming` `"idle"` keeps it warm.
- **compact-now**
  - Adds `compact_now`: `instructions` summary replaces old context. Auto-continues.
- **cd**
  - `/cd <dir>` and `change_dir`: move the session (history kept) to `<dir>` after the turn. Refused in a herdsman agent or a lead that owns herdsman agents.
- **tower-do-patch**
  - Adds `tower_do_patch`: change single tasks, no replay.
- **context-total**
  - `/context-total`: live context of session and agents. `footer on|off` toggles footer `agents Nk / tree N` (live agents without lead; tree tokens). `context-total.json`: `footer`, `intervalSeconds`.
- **pane-reaper**
  - Lead in herdr only. Closes finished idle lead-less panes. Only reports merged clean worktrees (any repo; `gh` check for GitHub origin only) and other orphans. Outside herdr: warns once.
  - `/pane-reaper` checks now, `on|off` toggles, `close <pane-id>` closes a reported one.
  - `pane-reaper.json`: `enabled`, `graceSeconds` (age to close), `intervalSeconds` (min 10).
- **diff-preview**
  - Long-ask preview (pi-compact-tools diff, else text) in the box. Scroll: wheel or Alt+Up/Down. On via `authorizerChain`.
- **permission-box**: centred accent overlay for prompt and preview.
- **lsp-defaults**
  - A Python project with `ty` or `ruff` on PATH (`ty` first) and no `pyright-langserver` or Python server in `.pi-lsp.json` gets `/lsp-config python ty server` or `/lsp-config python ruff server` once per session.
- **codemode-error-header**
  - Failed `codemode` header: `Script failed: <first error line>`.
- **popup-defer**
  - Holds dialogs while you type until a 1.5 s pause or 30 s. Printable keys are ignored 0.4 s after one opens. Never touches the draft.
  - `PI_POPUP_DEFER_MS`: pause in ms, `0` off. `/popup-defer on|off|<ms>` sets it per session.
- **Seed configs**
  - Written only when absent.
  - `extensions/pi-permission-system/config.json`: allow by default. `ask` for `git push`, forced or `-c` git, mutating `llm-prompts`/`gh`, edits to `rules`/`skills`/`workflows`/`agents` `.md`. `promptMaxRows`/`promptFieldMaxWidth` 1000000: prompt starts expanded.
  - `zentui.json`: `starship` footer: cwd, git, model, context, tokens, cost. Editor, user-message, selector-border restyle off.
  - `compact-tools.json`: `"style": "compact"` rows.
- **Packages**
  - Pinned: pi-herdsman (agent fleet), pi-herdr-tools (name/finish conversations), pi-ask-user (`ask_user`), pi-plan-mode (`/plan`), tower-do (task board), pi-notify (alerts), pi-lsp-extension (LSP), pi-permission-system (permissions), pi-zentui (footer), pi-web-access (web), pi-compact-tools (`/compact-tools`), pi-processes (`process`), pi-context-usage (context view), pi-cache-insight (cache misses).
