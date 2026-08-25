# Background agents: isolate in a worktree, then merge back and clean up

Applies to background-job sessions - those told they are "a background session" and given a `CLAUDE_JOB_DIR`. The isolation requirement comes from running unattended alongside the user's live checkout and other parallel jobs, not from any general preference for worktrees; a foreground session working directly with the user SHOULD just use the checkout it is given, per `planning.md`.

## Enter a worktree because you are forced to, not by default

- A background agent's cwd may already be the user's live checkout or another job's shared state, so before the first edit you MUST isolate into a worktree with `EnterWorktree`. Skip this only when the session is already inside a worktree it entered itself, or is working read-only.
- `EnterWorktree`'s default `baseRef: fresh` branches from `origin/<default-branch>`, which strands any work-in-progress on a local branch with unpushed commits. MUST check `git log --oneline <new-branch> ^origin/main` (or the equivalent for the target branch) immediately after entering, and rebase or re-branch onto the correct local ref before making any changes.

## Finish by merging back locally and removing the worktree

Once the task is done and committed inside the worktree:

1. **Fast-forward the original branch to the worktree branch, locally.** From wherever the target branch lives, `git merge --ff-only <worktree-branch>`. MUST confirm first that the target branch is a strict ancestor of the worktree branch (`git log --oneline <target>..<worktree-branch>` shows only the new work). MUST NOT create a merge commit for this.
2. **Remove the worktree and its branch.** Before calling `ExitWorktree` with `action: "remove"`, MUST verify the worktree branch is fully reachable from the branch you just fast-forwarded (`git merge-base --is-ancestor <worktree-branch> <target-branch>`); once it is, `discard_changes: true` loses nothing because every commit survives on `<target-branch>`.

- Do this locally only. Fast-forwarding into a local branch is not a push and does not need the explicit-confirmation gate, but push itself always requires asking first, per `git.md`.
- Skip step 1 and leave the worktree with `action: "keep"` only when the user has said not to merge, or when diverged history prevents a clean fast-forward - surface that instead of forcing a merge commit.
