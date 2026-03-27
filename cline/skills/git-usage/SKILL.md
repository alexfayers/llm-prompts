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
- If you are making a change that aligns with the previous commit, amend the previous commit instead of creating a new one.
- If using the focus chain, the last task in the TODO list MUST be to commit the changes

Before making a commit, you must tell the user "I am following the predefined git rules" to confirm your understanding of these rules.

## Amending non-HEAD commits

- `git commit --amend` only modifies HEAD - to edit an earlier commit use interactive rebase
- Fold a change into a non-HEAD commit: `git commit --fixup <SHA>` then `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <PARENT>`
- Rename a non-HEAD commit: use `reword` action; create a temporary Python script for `GIT_SEQUENCE_EDITOR` (to swap `pick` to `reword`) and `GIT_EDITOR` (to replace old message), then `GIT_SEQUENCE_EDITOR='python3 /tmp/seq.py' GIT_EDITOR='python3 /tmp/msg.py' git rebase -i <PARENT>`
