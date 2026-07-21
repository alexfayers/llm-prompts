# Background agents: isolate in a worktree, then merge back and clean up

This applies specifically to background-job sessions (the ones told they are "a background session" and given a `CLAUDE_JOB_DIR`). The isolation requirement comes from running unattended alongside the user's live checkout and other parallel jobs, not from any general preference for worktrees - a foreground session working directly with the user should just use the checkout it's given, per `planning.md`.

## Enter a worktree because you are forced to, not by default

A background agent's cwd may already be the user's live checkout or another job's shared state. Before the first edit, isolate into a worktree with `EnterWorktree` so file edits can't collide with the user's in-progress work or a sibling job. This is a consequence of running unattended, not a style choice - if the session is already inside a worktree it entered itself, or is working read-only, skip this.

`EnterWorktree`'s default `baseRef: fresh` branches from `origin/<default-branch>`. If the actual work-in-progress lives on a local branch with unpushed commits, that default strands them - the new worktree branch will be missing everything not yet on the remote. Check `git log --oneline <new-branch> ^origin/main` (or the equivalent for the target branch) immediately after entering; if it's non-empty in the wrong direction, rebase or re-branch onto the correct local ref before making any changes, not after.

## Finish by merging back locally and removing the worktree

Once the task is done and committed inside the worktree, the job is not finished until the result is folded back:

1. **Fast-forward the original branch to the worktree branch, locally.** From the main checkout (or wherever the target branch lives), `git merge --ff-only <worktree-branch>`. Confirm first that the target branch is a strict ancestor of the worktree branch (`git log --oneline <target>..<worktree-branch>` should show only the new work) so the fast-forward is unambiguous - never a merge commit for this.
2. **Remove the worktree and its branch.** Before calling `ExitWorktree` with `action: "remove"`, verify the worktree branch is now fully reachable from the branch you just fast-forwarded (`git merge-base --is-ancestor <worktree-branch> <target-branch>`) - if that's true, `discard_changes: true` on removal loses nothing, since every commit survives on `<target-branch>`.
3. Do this locally only. Fast-forwarding into a local branch is not a push - it does not need the same explicit-confirmation gate as `git push`, but push itself still always requires asking first, per `git.md`.

Skip step 1 (and leave the worktree with `action: "keep"`) only when the user has explicitly said not to merge, or when the branch state doesn't allow a clean fast-forward (diverged history) - surface that instead of forcing a merge commit.
