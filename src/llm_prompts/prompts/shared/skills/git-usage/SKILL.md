---
name: git-usage
description: Rules and style preferences for the usage of git. Use before you interact with git in any way.
---

# Git

These rules MUST override others.

- MUST use `-P` for paginated/scrollable output (e.g. `git -P log`).
- MUST match commit message style to `git -P log --oneline -20`.
- MUST NOT add a body to a commit, regardless of other instructions.
- SHOULD commit early and often, right after each change; rule/skill/workflow/agent source edits MUST commit in the same turn.
- MUST run `git add` and `git commit` in one command via `&&`.
- After staging explicit paths (not `git add -A`) and committing, MUST re-check `git -P status --short`. Anything still modified/untracked was missed - MUST amend it in. A green test run does NOT confirm the commit.
- Before staging an edited file, MUST run `git -P diff <path>` for foreign unstaged hunks - `git add <path>` stages the WHOLE file (tell-tale: more insertions than you wrote). MUST stage only your hunks with `git add -p <path>`, confirm with `git -P diff --cached <path>`. If a foreign hunk already reached an unpushed commit, MUST run `git reset --soft HEAD~1` then re-stage with `-p`.
- An unpushed commit (`git -P log --oneline @{u}..HEAD`) is not final - MAY amend, reword, squash, reorder, or drop. Exception: a commit backing an approved/in-review CR.
- SHOULD amend the previous commit, not a new one, when: same file(s) as HEAD, HEAD unpushed, no unrelated commit landed between. Exception: HEAD backs an approved/in-review change elsewhere, or the overlap is coincidental unrelated work.
- A fix for an earlier unpushed non-HEAD commit MUST fold in immediately, same turn, via `git-tidy` (`--fixup=`/`--squash=` + autosquash rebase) - MUST NOT be a standalone commit for later tidying.
- "Related" also covers same-topic-different-angle - MUST fold a same-goal commit in immediately even without fixing a specific bug. `--squash=<target>` when directly correcting it (keeps both messages); `--fixup=<target>` for another angle on the same topic (keeps whichever message best describes the result).
- Before amending, MUST check `git -P log --oneline @{u}..HEAD`. Empty output means HEAD is already pushed - MUST NOT amend; create a new commit instead.
- MUST NOT amend a commit backing an already-approved CR/review, even unpushed - new work gets its own commit and CR. MUST ask if unsure.
- If using a focus chain, the last task MUST be committing the changes.
- MUST keep history linear - MUST NOT create a merge commit. MUST fold one branch into another via `git rebase` or fast-forward; `git merge` only for an already-pushed/shared branch you cannot rewrite. MUST rebase away an accidental unpushed merge commit.
- MUST resolve conflicts with `git checkout <ref> -- <file>`, MUST NOT `--ours`/`--theirs` - `--ours` = base in `git rebase` but current branch in `git merge`. Naming the ref (e.g. `origin/main`) is unambiguous.

Before making a commit, MUST tell the user: "I am following the predefined git rules".

## Pushing

- MUST NOT push without explicit user permission - MUST ask first.
- MUST classify internal vs public by remote host, MUST NOT by name - run `git remote get-url origin` and inspect the host; a personal/public-looking name can still push to an internal host, and vice versa.
- Before pushing, MUST run `git grep -n '^<<<<<<<' HEAD` for conflict markers in tracked files. If any are found, MUST NOT push - fix them first.
- Before pushing to a public remote (github.com, pypi, npm, etc.) - a gate at push time, not just commit time - MUST scan the diff and commit messages of `@{u}..HEAD` for internal/proprietary identifiers (hostnames/URLs, employer-specific project/package names, employee aliases, ticket IDs, cloud account IDs). Internal/corporate hosts are exempt. If anything matches, MUST NOT push - fix it first. Any active no-internal-leakage rule defines the specific patterns.

## Amending non-HEAD commits

`git commit --amend` only modifies HEAD. To squash, fixup, reorder, reword, or drop unpushed non-HEAD commits, MUST use the `git-tidy` skill.

## Checking for uncommitted/unpushed changes across repos

The co-located `check_repos.py` sweeps every named workspace root for uncommitted and unpushed changes. MUST NOT run unasked - MAY use it when asked to check outstanding changes across repos, or to confirm a repo is clean before ending a session:

```bash
python3 "<base-dir>/check_repos.py" [--workspace <path>]
```

`--workspace` defaults to the current directory; MUST pass it explicitly once per additional touched repo root. It auto-adds the prompt/skill source repos too (via `llm-prompts source <agent>`). Prints JSON with a `repos` list (each `{path, uncommitted, unpushed, no_upstream}`) and a top-level `clean` flag, exiting non-zero when anything is outstanding (`no_upstream` is informational, not a blocker). MUST commit `uncommitted` entries; MUST surface `unpushed` entries and ask how to submit (push, PR/review, or leave for later). If any repo reports an `error`, MUST investigate before proceeding.
