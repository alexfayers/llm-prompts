---
name: llm-prompts-contribute
description: Open a PR in llm-prompts, cline-hooks, or mcp-memory - `llm-prompts contribute` for rule/skill/workflow/agent sources, gh otherwise, per-repo PR template/CONTRIBUTING.md. Use to open/update a PR.
---

# Opening a PR

Covers llm-prompts, cline-hooks, and mcp-memory - siblings with the same PR template shape and conventions. Read the TARGET repo's own CONTRIBUTING.md and `.github/PULL_REQUEST_TEMPLATE.md`; never assume another repo's copy applies.

## Rule/skill/workflow/agent sources (any repo's `**/prompts/**`)

cline-hooks and mcp-memory each carry their own prompts tree (rules, skills, workflows, agents) feeding the same distributed collection as llm-prompts' own - all three go through `llm-prompts contribute`, never a manual branch:

- Commit straight to that repo's local `main`.
- `llm-prompts contribute list` - shows every unmerged commit's derived branch and status (new/needs sync/ok) across configured overlay repos; `--tool NAME` narrows to one.
- `llm-prompts contribute sync --apply` - cherry-picks each pending commit onto a fresh disposable branch and force-pushes it. Re-run after amending/rewording the commit on `main` to re-derive.
- MUST NOT commit directly to a `contribute`-derived branch - the next `sync` overwrites it as regenerable from `main`.
- An orphan branch (source commit dropped from `main`) is auto-deleted by `sync --apply` if it has no open PR, or clean up manually with `sync --cleanup <branch>`.

## Everything else

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
- Title: conventional-commit format (`type: subject`).
- Description: bullet points, not paragraphs. State WHAT and WHY, not HOW. No restating the diff, no process commentary.
