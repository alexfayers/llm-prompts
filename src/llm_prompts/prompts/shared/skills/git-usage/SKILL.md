---
name: git-usage
description: Rules and style preferences for the usage of git. Use before you interact with git in any way.
---

# Git

These git rules override others.

- ALWAYS use `-P` for paginated/scrollable output (e.g. `git -P log`).
- Match commit message style to `git -P log --oneline -20`.
- NEVER add a body to a commit, regardless of other instructions.
- Commit early and often, right after each change; rule/skill/workflow/agent source edits commit in the same turn.
- Staging and committing together: run `git add` and `git commit` in one command via `&&`.
- After staging explicit paths (not `git add -A`) and committing, re-check `git -P status --short`. Anything still modified/untracked was missed - amend it in. A green test run does NOT confirm the file was committed.
- Before staging an edited file, run `git -P diff <path>` for foreign unstaged hunks - `git add <path>` stages the WHOLE file (tell-tale: more insertions than you wrote). Stage only your hunks with `git add -p <path>`, confirm with `git -P diff --cached <path>`. If a foreign hunk already reached an unpushed commit, `git reset --soft HEAD~1` then re-stage with `-p`.
- An unpushed commit (`git -P log --oneline @{u}..HEAD`) is not final - amend, reword, squash, reorder, or drop freely. Exception: a commit backing an approved/in-review CR.
- Prefer amending the previous commit over a new one when: same file(s) as HEAD, HEAD unpushed, no unrelated commit landed between. Skip only if HEAD backs an approved/in-review change elsewhere, or the overlap is coincidental unrelated work.
- A fix for an earlier unpushed non-HEAD commit: fold it in immediately, same turn, via `git-tidy` (`--fixup=`/`--squash=` + autosquash rebase) - never a standalone commit for later tidying.
- "Related" also covers same-topic-different-angle - fold a same-goal commit in immediately even without fixing a specific bug. `--squash=<target>` when directly correcting it (keeps both messages); `--fixup=<target>` for another angle on the same topic (keeps whichever message best describes the result).
- Before amending, check `git -P log --oneline @{u}..HEAD`. Empty output means HEAD is already pushed - do NOT amend; create a new commit instead.
- Do NOT amend a commit backing an already-approved CR/review, even unpushed - new work gets its own commit and CR. Ask if unsure.
- If using a focus chain, the last task MUST be committing the changes.
- Keep history linear - NEVER create a merge commit. Use `git rebase` (or fast-forward) to fold one branch into another; reserve `git merge` for an already-pushed/shared branch you cannot rewrite. Rebase away an accidental unpushed merge commit.
- Resolve conflicts with `git checkout <ref> -- <file>`, NEVER `--ours`/`--theirs` - meaning flips silently between `git rebase` (`--ours` = base) and `git merge` (`--ours` = current branch). Naming the ref (e.g. `origin/main`) is unambiguous either way.

Before making a commit, tell the user: "I am following the predefined git rules".

## Pushing

- NEVER push without explicit user permission - always ask first.
- Classify a repo as internal vs public by remote host, NEVER by name - run `git remote get-url origin` and inspect the host; a personal/public-looking name can still push to an internal host, and vice versa.
- Before pushing, run `git grep -n '^<<<<<<<' HEAD` to check for conflict markers in tracked files. If any are found, do not push - fix them first.
- Before pushing to a public remote (github.com, pypi, npm, etc.) - a hard gate at push time, not just commit time - scan the diff and commit messages of `@{u}..HEAD` for internal/proprietary identifiers (hostnames/URLs, employer-specific project/package names, employee aliases, ticket IDs, cloud account IDs). Internal/corporate hosts are exempt. If anything matches, do not push - fix it first. Any active no-internal-leakage rule defines the specific patterns.

## Amending non-HEAD commits

`git commit --amend` only modifies HEAD. To squash, fixup, reorder, reword, or drop unpushed non-HEAD commits, use the `git-tidy` skill.

## Checking for uncommitted/unpushed changes across repos

The co-located `check_repos.py` script sweeps every named workspace root for uncommitted and unpushed changes. Optional, never automatic - use it when asked to check outstanding changes across repos, or to confirm a repo is clean before ending a session:

```bash
python3 "<base-dir>/check_repos.py" [--workspace <path>]
```

`--workspace` defaults to the current directory; pass it explicitly once per additional touched repo root. It auto-adds the prompt/skill source repos too (shells out to `llm-prompts source <agent>` per supported agent). Prints JSON with a `repos` list (each `{path, uncommitted, unpushed, no_upstream}`) and a top-level `clean` flag, exiting non-zero when anything is outstanding (`no_upstream` is informational, not a blocker). For repos with `uncommitted` entries, commit them. For repos with `unpushed` entries, surface them and ask how to submit (push, PR/review, or leave for later). If any repo reports an `error`, investigate before proceeding.
