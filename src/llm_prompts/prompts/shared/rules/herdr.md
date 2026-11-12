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
- Every handoff MUST follow the `handoff` skill.
{% if AGENT == "pi" %}
- MUST update pi-herdsman or other pi packages only when no agents are running, then restart pi. A mid-session update blocks `delegate_agent` until restart.
{% endif %}

## Feature worktrees

- A coordinator running a parallel feature agent SHOULD open it in its own worktree with `herdr worktree open --workspace <id>` on branch `feat/<name>`.
- Children inherit the coordinator's cwd. MUST start the coordinator inside the worktree.
- A worktree agent MUST NOT run `llm-prompts update`. Main runs it after merging, because the install comes from the main checkout.
- A worktree needs its own `uv sync` and `uv run` venv.
- The pane-reaper extension only reports clean merged worktrees as safe to remove. Main MUST remove them, after merging: run `herdr worktree remove --workspace <id>`, then `git branch -d` the branch. Herdr keeps the branch.
- MUST NOT use raw `git worktree remove`, nor remove a dirty worktree or one with an unmerged commit.
