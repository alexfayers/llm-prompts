---
roles: lead
requires_command: herdr
---

# Herdr

- Handing work to a new agent in a Herdr pane or tab, MUST start it and send the prompt without `--wait`, then carry on - MUST NOT block on the new session.
- MUST NOT send `herdr agent prompt` to a pane a human may be typing in. MAY use it only for agent panes the user did not ask to talk in, or after the user approves. The `HANDOFF-ACK` reply to the sending pane is exempt: that agent pane ran the handoff and awaits it.
- To open work in a worktree, MUST link it under the current workspace with `herdr worktree open --workspace <id>`, not `herdr workspace create` - `<id>` from `herdr pane current --current`, never `$HERDR_WORKSPACE_ID`.
- Herdr links a worktree only into a workspace of the same git repo - MUST check its `repo_key` in `herdr workspace list` first.
- `agent start` returning `agent_not_ready` on a new path usually means a folder-trust prompt - MUST hand it to the user.
{% if AGENT == "pi" %}
- Handoff means writing it via the `handoff` skill and passing it to `compact_now`. MUST hand off to a new Herdr session only when the user asks for one, or the cwd, worktree, env or process must change.
{% endif %}
- Every handoff to a new session MUST go live to a new Herdr session, not to `HANDOFF.md`, unless the user asks for a disk handoff or has opted out in conversation or memory.
- Live handoff: MUST write the doc via the `handoff` skill, start an agent of the same kind in a new pane of the current tab, and send the doc as its prompt. The prompt MUST tell it to use `pickup` and to confirm its understanding of the asks to this session at the address below.
{% if AGENT == "claude-code" %}
  - MUST start the new session with `herdr agent start <new-name> --kind claude --pane <new-pane-id> -- --name <new-name>`, where `<new-pane-id>` is the new pane. Without `--name`, `ListAgents` shows it unnamed and `SendMessage` cannot reach it - the herdr name is only a pane label.
  - Address: this session's name from `ListAgents` (`<name>`) and this pane's ID (`<id>`) from `herdr pane current --current`. MUST send the handoff to the new session with `SendMessage`, not `herdr agent prompt`. Its FIRST LINE MUST be exactly `HANDOFF-ACK <id>` alone, above any heading, naming this sending pane, never the new session. The `pickup` instruction follows it, then the doc. The new session replies with `SendMessage` to `<name>`.
{% else %}
  - Address: this pane's ID (`<id>`) from `herdr pane current --current`. The prompt's FIRST LINE MUST be exactly `HANDOFF-ACK <id>` alone, above any heading, naming this sending pane, never the new session. The `pickup` instruction follows it, then the doc. The new session replies with `herdr agent prompt <id>`, or through a subagent when it has no shell.
{% endif %}
- MUST confirm the new agent is running from `herdr agent get`, not from its own words.
- MUST NOT close the old session's pane until a reply containing `HANDOFF-ACK <id>` has arrived. Where the reply asks for more, MUST answer and wait for the next reply. Once a reply needs nothing more, MUST close only its own pane (`herdr pane close <id>`) as the last step.
- On any failure, or if the reply never arrives, MUST keep the old pane open and report to the user. MUST NOT resend a stalled prompt.
{% if AGENT == "pi" %}
- MUST update pi-herdsman or other pi packages only when no agents are running, then restart pi. A mid-session update blocks `delegate_agent` until restart.
{% endif %}

## Feature worktrees

- A coordinator running a parallel feature agent SHOULD open it in its own worktree with `herdr worktree open --workspace <id>` on branch `feat/<name>`.
- Children inherit the coordinator's cwd. MUST start the coordinator inside the worktree.
- Each worktree agent MUST make at most one commit and MUST NOT push.
- Main integrates that commit by fast-forward, rebase or cherry-pick. A fixup onto the unpushed commit is fine.
- A worktree agent MUST NOT run `llm-prompts update`. Main runs it after merging, because the install comes from the main checkout.
- A worktree needs its own `uv sync` and `uv run` venv.
- The pane-reaper extension only reports clean merged worktrees as safe to remove. Main MUST remove them, after merging: run `herdr worktree remove --workspace <id>`, then `git branch -d` the branch. Herdr keeps the branch.
- MUST NOT use raw `git worktree remove`, nor remove a dirty worktree or one with an unmerged commit.
