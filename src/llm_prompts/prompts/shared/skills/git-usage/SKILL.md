---
name: git-usage
description: Rules and style preferences for the usage of git. Use before you interact with git in any way.
---

# Git

_Note that these git rules override others._

- When running `git` commands that can return paginated or scrollable output (such as `git log`), ALWAYS use the `-P` option (e.g. `git -P log`)
- Commit messages MUST maintain a style consistent with previous commits in the repository. ALWAYS use `git -P log --oneline -20` to see the style of the most recent commits so that you can match it.
- **Never** add a body to a commit, regardless of other instructions.
- _Always_ make a commit after completing a change.
- Commits _must_ be created frequently - early and often, following best practices
- When staging and committing modified files at the same time, run `git add` and `git commit` in a single commit by using `&&` instead of staging and committing separately.
- When staging files **explicitly by path** (rather than `git add -A`), re-check `git -P status --short` immediately after committing. If any file you intended to include is still listed as modified/untracked, you missed it - amend it in (a build/test run can mask this by reading the working tree, so green tests do NOT confirm the file was committed).
- **Before staging a file you edited, run `git -P diff <path>` to check for pre-existing hunks that are not yours.** `git add <path>` stages the WHOLE file, so any foreign unstaged edit in that file gets folded into your commit (tell-tale: more insertions than you wrote). When a file carries edits you did not make, stage only your hunks with `git add -p <path>` and confirm with `git -P diff --cached <path>` before committing. If a foreign hunk already slipped into an unpushed commit, recover with `git reset --soft HEAD~1` then re-stage with `-p`.
- If you are making a change that aligns with the previous commit, amend the previous commit instead of creating a new one. **Concrete trigger, check every time before running `git commit`:** if the file(s) you are about to commit are the same file(s) HEAD touched, and HEAD is unpushed, and no other unrelated commit landed in between - that is "aligns with the previous commit." Default to amending; only create a new commit if you can name a reason the two changes are independent (e.g. HEAD already backs an approved/in-review change elsewhere, or genuinely unrelated work landed on the same file by coincidence).
- **Before amending**, check if HEAD has been pushed with `git -P log --oneline @{u}..HEAD`. If the output is empty, HEAD is already pushed - do NOT amend. Create a new commit instead.
- **Also do NOT amend a commit that backs an already-approved CR/review**, even if it is unpushed - a new, separate piece of work belongs in its own commit (and its own CR). Amending silently folds new code into an approved review. If unsure whether the previous commit is approved, ask the user before amending.
- If using the focus chain, the last task in the TODO list MUST be to commit the changes

Before making a commit, you must tell the user "I am following the predefined git rules" to confirm your understanding of these rules.

## Pushing

- **NEVER** push without explicit user permission. Always ask first.
- **Classify a repo as internal vs public by its remote host, NEVER by its name.** Always run `git remote get-url origin` and inspect the host before deciding whether a repo is internal or public - a repo whose name looks personal/public may push to an internal host, and vice versa. Do not infer the host from the repo/package name.
- Before pushing, run `git grep -n '^<<<<<<<' HEAD` to verify no conflict markers exist in tracked files. If any results are found, **do not push** - fix them first.
- **Before pushing to a public remote (github.com, pypi, npm, etc.), you MUST scan the outgoing commits for internal/proprietary leakage** - this is a hard gate, do it at push time, not just at commit time. Check `git remote get-url origin` to classify the remote; internal/corporate git hosts are exempt. For public remotes, scan BOTH the diff and the commit messages of `@{u}..HEAD` for any internal identifiers your environment defines (internal hostnames/URLs, employer-specific project or package names, employee aliases, internal ticket IDs, cloud account IDs). If anything matches, **do not push** - fix it first. Any active no-internal-leakage rule defines the specific patterns.

## Amending non-HEAD commits

- `git commit --amend` only modifies HEAD - to edit an earlier commit use interactive rebase
- Fold a change into a non-HEAD commit: `git commit --fixup <SHA>` then `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <PARENT>`
- Rename a non-HEAD commit: use `reword` action; create a temporary Python script for `GIT_SEQUENCE_EDITOR` (to swap `pick` to `reword`) and `GIT_EDITOR` (to replace old message), then `GIT_SEQUENCE_EDITOR='python3 /tmp/seq.py' GIT_EDITOR='python3 /tmp/msg.py' git rebase -i <PARENT>`
