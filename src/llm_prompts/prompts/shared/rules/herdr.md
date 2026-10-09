---
roles: lead
requires_command: herdr
---

# Herdr

- Handing work to a new agent in a Herdr pane or tab, MUST start it and send the prompt without `--wait`, then carry on - MUST NOT block on the new session.
- To open work in a worktree, MUST link it under the current workspace with `herdr worktree open --workspace <id>`, not `herdr workspace create` - `<id>` from `herdr pane current --current`, never `$HERDR_WORKSPACE_ID`.
- Herdr links a worktree only into a workspace of the same git repo - MUST check the workspace's `repo_key` in `herdr workspace list` before choosing the path.
- `agent start` returning `agent_not_ready` on a new path usually means a folder-trust prompt - MUST hand it to the user.
{% if AGENT == "pi" %}
- MUST hand off to a new Herdr session only when the cwd, worktree, env or process must change. Otherwise MUST compact with `compact_now`.
{% endif %}
- Handing off to a new session via Herdr, MUST start it in a new tab, confirm its agent is running (`herdr agent get`), then close the old session's tab.

## Feature worktrees

- A coordinator running a parallel feature agent SHOULD open it in its own worktree with `herdr worktree open --workspace <id>` on branch `feat/<name>`.
- Children inherit the coordinator's cwd. MUST start the coordinator inside the worktree.
- Each worktree agent MUST make at most one commit and MUST NOT push.
- Main integrates that commit by fast-forward, rebase or cherry-pick. A fixup onto the unpushed commit is fine.
- A worktree agent MUST NOT run `llm-prompts update`. Main runs it after merging, because the install comes from the main checkout.
- A worktree needs its own `uv sync` and `uv run` venv.
- The pane-reaper extension only reports clean merged worktrees as safe to remove. Main MUST remove them, after merging: run `herdr worktree remove --workspace <id>`, then `git branch -d` the branch. Herdr keeps the branch.
- MUST NOT use raw `git worktree remove`. MUST NOT remove a dirty worktree or one with an unmerged commit.
