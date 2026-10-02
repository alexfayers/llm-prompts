---
name: llm-prompts-contribute
description: Open a PR in llm-prompts, cline-hooks, or mcp-memory - `llm-prompts contribute` for rule/skill/workflow/agent sources, gh otherwise, per-repo PR template/CONTRIBUTING.md. Use to open/update a PR.
---

# Opening a PR

Covers llm-prompts, cline-hooks, and mcp-memory - siblings with the same PR template shape and conventions. Read the TARGET repo's own CONTRIBUTING.md and `.github/PULL_REQUEST_TEMPLATE.md`; never assume another repo's copy applies.

## Rule/skill/workflow/agent sources (any repo's `**/prompts/**`)

cline-hooks and mcp-memory each carry their own prompts tree (rules, skills, workflows, agents) feeding the same distributed collection as llm-prompts' own - all three go through `llm-prompts contribute`, never a manual branch:

- Commit straight to that repo's local `main`.
- `llm-prompts contribute list` - shows every unmerged commit's batch branch and status (new/current/stale/regressed/in another PR) across configured overlay repos; `--tool NAME` narrows to one.
- Pending commits are grouped into batches of up to 5, appended in order to the newest open `<login>/contribute/<slug>` branch with room; a full or merged batch starts a new one.
- `llm-prompts contribute sync --apply` - a batch whose commits are all current gets new ones cherry-picked on top and pushed normally; a batch with an amended or missing commit is rebuilt from `main` and pushed with `--force-with-lease`. It also opens a draft PR, no reviewers, for each pushed batch branch lacking an open PR; the body follows the target repo's template with What listing the batch's commit subjects.
- `llm-prompts contribute sync --commit SHA` (repeatable) - syncs only the batches holding those commits, appending to the newest open batch with room or starting a new one; everything else stays local.
- `llm-prompts contribute update --apply` - rebases your open PRs that are behind `main`.
- `sync --commit A --commit B` naming commits in different repos links them: the first named is the dependency; its repo syncs first, and the dependent's batch stays local until the dependency is pushed.
- `list` prints each linked commit's dependency on its own line, `-> depends on <pr url>` (or `<tool>: unpushed`/`no PR yet`), red when it blocks; sync writes it into the `What` section as `Depends on <url>`, and rewrites only the `What` section when a batch's commits change.
- A commit already in another of your open PRs is skipped and listed as in that PR.
- MUST NOT commit directly to a batch branch - `sync` may rebuild it as regenerable from `main` and overwrite it.

## Everything else

- `llm-prompts contribute` works without gh given a GH_TOKEN or GITHUB_TOKEN.
- Marking a contribute PR ready for review enables squash auto-merge.
- Push your own branch, open a PR against `main`.
- Check push access first: `gh repo view --json viewerPermission`.
  - `WRITE`/`MAINTAIN`/`ADMIN`: `git push -u origin <branch>` then `gh pr create --fill`.
  - Otherwise: `gh repo fork --remote`, push to the fork, `gh pr create --fill --head <username>:<branch>`.
- To update an open PR: amend/rebase locally and force-push the same branch. MUST NOT add new commits.

## Before opening

- Run the target repo's `just` (lint, type-check, test) - its own CONTRIBUTING.md is authority for the exact recipes (e.g. mcp-memory adds a naming-check).
- Any changed rule/skill/workflow/agent file MUST stay within its prompt size budget.

## PR content

- Follow the target repo's `.github/PULL_REQUEST_TEMPLATE.md` structure (What/Why/Testing/Checks - the Checks bullet differs per repo).
- Right after `sync` opens a PR, MUST fill Why and Testing via `gh pr edit <url> --body-file -`, at most 3 bullets per section, fewer where possible, each one short line not restating the title - Why gives the reasoning, merging related commits into one bullet; Testing is usually 1 bullet. Commits carry no body, so sync cannot write Why. Descriptions MUST be very easy for reluctant reviewers to understand, with clear reasoning.
- Title: conventional-commit format (`type: subject`).
- Description: bullet points, not paragraphs. State WHAT and WHY, not HOW. No restating the diff, no process commentary.
- Planned with eagle-vision (you built it from a plan directory, or the user names one): once the PR is open, post the plan as a separate comment - `python3 "<base-dir>/../eagle-vision/focus.py" comment <dir> | gh pr comment <pr-url> --body-file -`. Post it once, never in the description.
