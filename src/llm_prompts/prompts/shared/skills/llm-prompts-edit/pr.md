# Opening the change as a PR

Use the `gh` CLI.

- A PR holds at most 2 commits: one compression commit (only if needed) and one rule-change commit.
- Check push access first: `gh repo view --json viewerPermission`. With `WRITE`/`MAINTAIN`/`ADMIN`, push the branch directly and open the PR from it - no fork needed:
  - `git push -u origin <branch>`
  - `gh pr create --fill`
- Without push access, fork first:
  - `gh repo fork --remote`
  - push the branch to the fork
  - `gh pr create --fill --head <your-username>:<branch>`
- If the PR needs changes after opening, amend/rebase locally and force-push the same branch. MUST NOT add new commits to update an open PR.
