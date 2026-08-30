---
name: git-tidy
description: "Tidy unpushed commit history via a non-interactive rebase: squash, fixup, reorder, reword, or drop commits. Use when asked to tidy, clean up, squash, reorder, reword, or drop unpushed commits."
---

# Git Tidy

## Hard invariants

- Only rewrite unpushed commits - `git -P log --oneline @{u}..HEAD` MUST include every commit touched.
- MUST NOT use `--no-verify`, MUST NOT `git rebase --skip` on conflict - resolve properly or `git rebase --abort`.
- MUST NOT auto-push. Pushing is a separate, explicitly confirmed step (`confirm-push` skill) - out of scope here.
- MUST present the planned end-state and get explicit confirmation before any rewrite.

## Workflow

1. **Run the safety gate**:

   ```bash
   python3 "<base-dir>/inspect_range.py" [base]
   ```

   `base` optional (default: upstream `@{u}`, falling back to `--root` with no upstream). Prints JSON (`base`, `working_tree_dirty`, `commit_count`, `commits`, `has_merge_commits`, `has_pushed_commits`, `safe_to_rewrite`); exits non-zero if the tree is dirty, the range has pushed commits, or contains a merge commit (rebasing across a merge is out of scope). Exit code 2: no resolvable base.

2. **Present the plan** - commit list/order/messages - and get explicit confirmation before touching history.

3. **Execute via a non-interactive scripted rebase** - never hand-edit the interactive todo list live:
   - **Fold one commit into another only (fixup/squash/reword), no reordering**: use `--autosquash` - simpler than `rewrite_range.py`, and works on non-adjacent commits by finding the `fixup!`/`squash!`/`amend!`-prefixed commit anywhere in the range.
     - **Fixup** (discard new commit's message): `git commit --fixup=<target-SHA>`, then `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <base>` (`--root` if the range includes the first commit).
     - **Squash** (combine both messages, opens editor): `git commit --squash=<target-SHA>`, then the same `--autosquash` rebase.
     - **Reword** (message only, no content change): `git commit --fixup=reword:<target-SHA>` opens `$GIT_EDITOR` pre-filled with `amend! <original subject>` plus the original body - MUST preserve the `amend! <subject>` title line (see Anti-patterns), then the same `--autosquash` rebase.
     - Staging new work meant to fold into an existing unpushed commit: commit straight to `--fixup=`/`--squash=`, skip a separate fold step.
   - **Reorder, drop, or combine folding with reordering**: `--autosquash` cannot reorder or drop, use the plan-driven script instead:

     ```bash
     python3 "<base-dir>/rewrite_range.py" <plan.json> [base]
     ```

     Plan is a JSON array, oldest-first, final top-to-bottom rebase order: `[{"sha": "...", "verb": "pick"}, {"sha": "...", "verb": "squash", "message": "final subject"}, ...]`. `verb`: `pick`/`drop`/`squash`/`fixup`/`reword`. `message` optional, only meaningful on `squash`/`reword` - sets the final subject; omit to keep git's default. Replaces hand-written `GIT_SEQUENCE_EDITOR`/`GIT_EDITOR` scripts - never write those by hand.
     - `squash`/`fixup` always fold into the nearest previous kept commit - purely positional, never path-based.
     - Preflight: identify topic boundaries (e.g. feat/docs/fix groups), ensure each `squash`/`fixup` line sits immediately below the commit it should fold into. Keep a topic block's first commit as `pick`/`reword`, fold only subsequent commits in that block.
     - Example: combine two docs commits, keep an earlier feature commit separate - `pick <feature>`, `reword <docs-1>`, `fixup <docs-2>` - never `squash <docs-1>`.
   - On conflict: resolve properly, or `git rebase --abort` (restores history byte-identical to before). Never `--skip`.

4. **Verify.** Build/test the project (follow `pre-implementation` and the project's build skill) before declaring done.

5. **Stop and report** the new commit history to the user. Do not push - separate, explicitly confirmed step.

## Anti-patterns

- `git rebase --skip` on conflict - silently drops that commit's changes.
- Dropping the `amend! <subject>` title line when overwriting a `--fixup=reword` message - `--autosquash` matches on that prefix; missing it silently leaves the commit unfolded with no error.
- Squashing or reordering commits that aren't actually related.
- Using `squash` (not `reword`/`pick`) on the first commit of a new topic block (e.g. docs after feat) - silently folds it into the prior commit.
- Attempting this on a range containing a merge commit - the safety gate blocks it; treat that as a separate, higher-risk task.
