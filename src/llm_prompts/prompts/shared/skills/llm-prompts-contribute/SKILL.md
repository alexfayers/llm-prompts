---
name: llm-prompts-contribute
description: Open a PR in llm-prompts, cline-hooks, or mcp-memory. Use to open or update a PR.
---

# Opening a PR

Covers llm-prompts, cline-hooks, and mcp-memory. Read the TARGET repo's CONTRIBUTING.md and `.github/PULL_REQUEST_TEMPLATE.md`. Never assume another repo's applies.

- MUST open every PR as a draft (`gh pr create --draft`). MUST NOT request reviewers unasked.
- MUST NOT rewrite commits backing an approved or in-review PR/CR. New work MUST get its own commit and PR/CR. MUST ask if unsure.
- MUST get different-model review and fix notes until re-review has none. Then MUST mark ready and enable squash auto-merge. MUST NOT use `--admin`.

## Rule/skill/workflow/agent sources (any repo's `**/prompts/**`)

All three repos' prompts trees go through `llm-prompts contribute` (`list`, `sync`, `update`), never a manual branch. Each worktree branch is one PR:

- MUST work in a `git worktree` on your own branch with its commits ahead of `origin/main`, or of the worktree it depends on. Any number is allowed. `list` flags a worktree whose combined diff is over the line limit in `yappy_limits.json`.
- MUST start the worktree from `origin/main`, or from the lower worktree's branch and link it with `--depends-on`. `sync` skips a branch holding another worktree's commits or other local `main` commits (`skipped: holds commits of <branch>`).
- `sync --tool NAME --branch B` records the worktree, local only. `sync` copies the worktree into local `main` as one squashed commit (first commit's subject) and pulls remote changes, but never pushes it or touches a PR.
- `sync --tool NAME --ready B` lets `sync --apply` push B as `<login>/contribute/B` and open a draft PR (no reviewers), body per the repo's template, then refresh its title and What. `--local B` reverses it. `--forget B` drops it.
- `sync --rescan` records your open PRs checked out in worktrees, local only.
- `sync` is a dry run until `--apply`. It force-pushes only a draft PR whose remote branch is unchanged since the last sync. Once the PR merges, `sync --apply` removes the worktree and branch.
- `list` - shows each recorded worktree and its state, offline.
- `update --apply` - rebases your open PRs behind `main`.
- MUST NOT commit to local `main` for a recorded worktree. `sync` overwrites its copy.

## Everything else

- `llm-prompts contribute` works without gh given GH_TOKEN or GITHUB_TOKEN.
- MUST keep each repo's primary checkout on `main`. MUST work in a `git worktree` on your own branch. MUST NOT use a fresh clone.
- PRs come from worktrees via `llm-prompts contribute`. Stack or link PRs only with `sync --depends-on`. Sync writes the `Depends on` lines. A change building on one of your open PRs MUST be its own PR. MUST NOT copy another PR's commits outside a `sync --depends-on` stack, or add rebase notes.
- Shared CI logic MUST live in llm-prompts. Other repos MUST import it, never copy it.
- Check push access with `gh repo view --json viewerPermission`.
  - `WRITE`/`MAINTAIN`/`ADMIN`: `git push -u origin <branch>` then `gh pr create --draft --fill`.
  - Otherwise: `gh repo fork --remote`, push to the fork, `gh pr create --draft --fill --head <username>:<branch>`.
- To change a PR, MUST fold fixes into its commit with `git commit --fixup=<sha>` and `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <base>`, push with `--force-with-lease`, and edit the PR in place. MUST close only a dropped PR.

## Before opening

- Run the target repo's `just` (lint, type-check, test).
- Changed rule/skill/workflow/agent files MUST stay within their prompt size budget. In llm-prompts, SHOULD link the user to CI's size-report comment after opening.
- Before each push, MUST pass the repo's gate, then run the leak scan in a separate tool call. Manual PR branches MUST contain exactly one commit in `origin/main..HEAD`. MUST push with a timeout, using `--force-with-lease` only after rewriting. After each PR create or update, MUST watch CI and fix failures.

## PR content

- Follow the template structure (What/Why, optional Dependencies/Issues).
- After `sync` opens a PR, MUST fill Why (left empty) and delete the unused Dependencies and Issues placeholder comments via `gh pr edit <url> --body-file -`. The body MUST NOT contain `<!--`. Use at most 3 short bullets per section, not restating the title. Descriptions MUST be easy for reluctant reviewers to follow.
- Title: the first commit's subject (`type: subject`), plus `(+N more)` when the PR has more commits.
- Description: bullet points, not paragraphs, each a full sentence. State WHAT and WHY, not HOW. No restating the diff, no process commentary.
- If you used an eagle-vision plan directory or the user names one, MUST post the plan once as a separate PR comment: `python3 "<base-dir>/../eagle-vision/focus.py" comment <dir> | gh pr comment <pr-url> --body-file -`. MUST NOT put it in the description.
