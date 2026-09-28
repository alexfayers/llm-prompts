---
requires_command: herdr
---

# Herdr

- Handing work to a new agent in a Herdr pane or tab, MUST start it and send the prompt without `--wait`, then carry on - MUST NOT block on the new session.
- To open work in a worktree, MUST link it under the current workspace with `herdr worktree open --workspace <id>`, not `herdr workspace create` - `<id>` from `herdr pane current --current`, never `$HERDR_WORKSPACE_ID`.
- Herdr links a worktree only into a workspace of the same git repo - MUST check the workspace's `repo_key` in `herdr workspace list` before choosing the path.
- `agent start` returning `agent_not_ready` on a new path usually means a folder-trust prompt - MUST hand it to the user.
- Handing off to a new session via Herdr, MUST start it in a new tab, confirm its agent is running (`herdr agent get`), then close the old session's tab.
