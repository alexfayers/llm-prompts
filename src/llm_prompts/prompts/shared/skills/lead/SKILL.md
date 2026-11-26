---
name: lead
description: Run a pipeline of delegates that write, review and merge many PRs or code reviews. Use when a lead session staffs several changes at once.
---

# lead

## Intake

- MUST file each new problem as a short issue with success criteria before starting its writer.
- MUST get the user's approval for any item they did not ask for.
- MUST track each item as its own memory `task/` entity.
- SHOULD order work by what improves the workflow now first.

## Writers

- MUST start one writer delegate per issue or change, each in its own worktree or the repo's isolated workspace mechanism.
  Where the delegate tool takes `branch` and `base` (e.g. `fork`), MUST pass them so the writer makes its own PR branch, and MUST NOT make a landing checkout.
- Each writer task MUST be self-contained: the issue, the branch, the repo's test command,
  the leak scan for a public remote, and opening a draft PR or review.

## Reviewers

- MUST start one reviewer delegate per PR, and SHOULD resume that same warm reviewer for each re-review.
- Reviewers MUST follow `pr-review`'s `review-loop.md`: rate likelihood, and block only on likely, data-loss or secret findings.

## Results

- `CLEAN` -> MUST mark the PR ready with auto-merge through the repo's own ready or merge command,
  else mark it ready and enable auto-merge. Add an owner-review label first where the repo needs one.
  MUST NOT rebase it by hand where the repo's automation rebases auto-merge PRs. Otherwise rebase it on the base.
- Findings -> MUST resume that PR's writer with the findings.
- Conflicts -> MUST have a writer rebase the branch.

## Watching

- MUST run one background watch over all the user's open PRs or reviews across the repos, with the watch command the rules name, in follow mode.
- MUST NOT start one watch per change, nor poll in the foreground.
- On each merge, MUST record it in memory and resolve its task.
- MUST restart the watch after a reload.

## Staffing

- SHOULD keep the delegate count near the configured cap, and refill it after every result, within the in-flight review limit.
