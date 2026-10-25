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

All three repos' prompts trees go through `llm-prompts contribute` (`list`, `sync`, `update`), never a manual branch:

- Squash your worktree branch into that repo's local `main` as one commit.
- `list` - shows each unmerged commit's batch branch and status (new/current/stale/regressed/in another PR) across repos. `--tool NAME` narrows to one.
- Pending commits group into batches of up to 5, appended to the newest `<login>/contribute/<slug>` branch with no PR or a draft PR and room. A full, merged or ready batch starts a new one.
- `sync --apply` - a batch whose commits are all current gets new ones cherry-picked on top and pushed. A batch with an amended or missing commit is rebuilt from `main` and pushed with `--force-with-lease`. It opens a draft PR (no reviewers) for each pushed branch lacking one, body per the repo's template with What listing the commit subjects.
- `sync --commit SHA` (repeatable) - syncs only batches holding those commits. The rest stay local.
- `update --apply` - rebases your open PRs behind `main`.
- `sync --commit A --commit B` naming commits in different repos links them. The first named is the dependency and its repo syncs first. The dependent's batch stays local until then.
- `list` prints each linked commit's dependency, `-> depends on <pr url>` (or `<tool>: unpushed`/`no PR yet`), red when it blocks. `sync` writes it at the bottom of the PR body as `Depends on <url>`. When a batch's commits change, it rewrites only `What` and those lines.
- A commit already in another of your open PRs is skipped.
- MUST NOT commit directly to a batch branch. `sync` may overwrite it.

## Everything else

- `llm-prompts contribute` works without gh given GH_TOKEN or GITHUB_TOKEN.
- MUST keep each repo's primary checkout on `main`. MUST work in a `git worktree` on your own branch, then squash the result into local `main` as one commit. MUST NOT use a fresh clone.
- PRs come from local `main` via `llm-prompts contribute`. A code-only or mixed commit it skips MUST be cherry-picked onto a branch off `origin/main`, pushed, and opened against `main`. MUST NOT stack PRs.
- MUST order PRs only with `Depends on #N` under `## Dependencies`. A change building on one of your open PRs MUST be its own PR. MUST NOT copy another PR's commits or add rebase notes.
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
- Title: the commit subject, unchanged (`type: subject`).
- Description: bullet points, not paragraphs, each a full sentence. State WHAT and WHY, not HOW. No restating the diff, no process commentary.
- If you used an eagle-vision plan directory or the user names one, MUST post the plan once as a separate PR comment: `python3 "<base-dir>/../eagle-vision/focus.py" comment <dir> | gh pr comment <pr-url> --body-file -`. MUST NOT put it in the description.
