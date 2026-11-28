# Opening a PR

Covers llm-prompts, cline-hooks and mcp-memory. Read the TARGET repo's CONTRIBUTING.md and `.github/PULL_REQUEST_TEMPLATE.md`. Never assume another repo's applies.

- MUST open every PR as a draft. MUST NOT request reviewers unasked.
- MUST NOT rewrite commits backing an approved or in-review PR. New work MUST get its own commit and PR. MUST ask if unsure.
- MUST get different-model review and fix notes until re-review has none. Then MUST mark ready and enable squash auto-merge. MUST NOT use `--admin`.

## Rule/skill/workflow/agent sources (any repo's `**/prompts/**`)

All three repos' prompts go through `llm-prompts contribute` (`list`, `sync`, `update`), never a manual branch. Each worktree branch is one PR:

- MUST work in a `git worktree` on your own branch with its commits ahead of `origin/main`, any number of them.
  `list` flags a worktree whose combined diff exceeds the line guideline in `yappy_limits.json`.
- MUST start the worktree from `origin/main`. A change that needs another unmerged change in the same repo MUST go in that change's worktree and PR, never a stacked PR.
  `sync` skips a branch holding another worktree's or other local `main` commits.
- `sync --tool NAME --branch B` records the worktree, local only.
  `sync` copies it into local `main` as one squashed commit and pulls remote changes, never pushing or touching a PR.
- `sync --tool NAME --why B "TEXT"` records the Why for B's PR, local only. MUST record it before `--ready`. `sync` skips a PR (nonzero exit) while a required template section is empty.
- `sync --tool NAME --ready B` lets `sync --apply` push B as `<login>/contribute/B` and open a draft PR (no reviewers), body per the repo's template,
  then refresh its What, and its title only while it is still the one sync wrote. `--local B` reverses it. `--forget B` drops it.
- `sync --rescan` records your open PRs in worktrees, local only. `--only B` syncs B alone.
- `sync` is a dry run until `--apply`. It force-pushes only a draft PR whose remote branch is unchanged since the last sync. Once the PR merges, `sync --apply` removes the worktree and branch.
- `list` shows each worktree's state, offline.
- `update --apply` rebases your open PRs behind `main`, leaving auto-merge PRs to the rebase queue unless `--include-auto-merge` or `--pr` names them.
- MUST NOT edit local `main` by hand. `update` copies ready worktrees into it, then installs. On a conflict that prints a worktree, MUST resolve its files, `git add`, rerun.

## Everything else

- `llm-prompts contribute` works without gh given GH_TOKEN or GITHUB_TOKEN.
- MUST keep each repo's primary checkout on `main`, work in a `git worktree` on your own branch, never a fresh clone.
- Every PR SHOULD target `main`. Link PRs across repos only with `sync --depends-on` (`TOOL:BRANCH` or `owner/repo#N`).
  Sync writes the `Depends on` lines. MUST NOT copy another PR's commits or add rebase notes.
- Shared CI logic MUST live in llm-prompts. Other repos MUST import it, never copy it.
- Check push access with `gh repo view --json viewerPermission`.
  - `WRITE`/`MAINTAIN`/`ADMIN`: `git push -u origin <branch>` then `gh pr create --draft --fill`.
  - Otherwise: `gh repo fork --remote`, push to the fork, `gh pr create --draft --fill --head <username>:<branch>`.
- To change a PR, MUST fold fixes into its commit with `git commit --fixup=<sha>` and `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <base>`, push with `--force-with-lease`,
  and edit the PR in place. MUST close only a dropped PR.

## Before opening

- MUST set the issue's status per `{{SKILL_DIR}}/issue-rules.md`: `In progress` when a writer starts.
- Run the target repo's `just`.
- Changed rule/skill/workflow/agent files MUST stay within their size budget. In llm-prompts, SHOULD link the user to CI's size-report comment after opening.
- Before each push, MUST pass the repo's gate, then run the leak scan in its own tool call. Manual PR branches MUST contain exactly one commit in `origin/main..HEAD`.
  MUST push with a timeout, using `--force-with-lease` only after rewriting. After each PR create or update, MUST watch CI and fix failures.

## PR content

- Follow the template (What/Why, optional Dependencies/Issues).
- `sync` writes the recorded Why and no placeholder comments. A body edit MUST NOT contain `<!--`. Sync marks its What bullets with `[](#sync)`.
  Use at most 3 short bullets per section, not restating the title. Descriptions MUST be easy for reluctant reviewers to follow.
- Title: first commit's subject, plus `(+N more)`. It is the squash subject: a multi-commit PR MUST set one with `--title B "TEXT"`.
- Description: full-sentence bullets stating WHAT and WHY, not HOW. No diff restating or process notes.
- If you used an eagle-vision plan directory or the user names one, MUST post the plan once as its own PR comment:
  `python3 "{{SKILL_DIR}}/../eagle-vision/focus.py" comment <dir> | gh pr comment <pr-url> --body-file -`. MUST NOT put it in the description.
