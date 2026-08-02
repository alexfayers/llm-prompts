---
name: git-tidy
description: "Tidy up local commit history before pushing - squash, fixup, reorder, reword, and drop unpushed commits via a scripted non-interactive rebase. Use when asked to tidy, clean up, squash, reorder, or reword commits, or to prepare a branch's history for review."
---

# Git Tidy

## When to use

The user asks to tidy, clean up, squash, reorder, or reword commits, or to prepare a branch's history for review/push.

## Hard invariants

- Only ever rewrite commits that are unpushed. `git -P log --oneline @{u}..HEAD` must include every commit being touched.
- Never use `--no-verify` and never `git rebase --skip` on conflict. If a rebase conflicts, resolve it properly or `git rebase --abort`.
- Never auto-push. Pushing is a separate, explicitly confirmed step (the `confirm-push` skill) - out of scope here.
- Always present the planned end-state to the user and get explicit confirmation before running any rewrite.

## Workflow

1. **Run the safety gate**:

   ```bash
   python3 "<base-dir>/inspect_range.py" [base]
   ```

   `base` is an optional base ref (default: the branch's upstream, `@{u}`, falling back to `--root` when there is no upstream). It prints JSON (`base`, `working_tree_dirty`, `commit_count`, `commits`, `has_merge_commits`, `has_pushed_commits`, `safe_to_rewrite`) and exits non-zero when the working tree is dirty, the range already contains pushed commits, or the range contains a merge commit - rebasing across a merge is a separate, higher-risk operation this skill does not attempt. Exit code 2 means no resolvable base (e.g. the repo has no commits yet).

2. **Present the plan.** Show the user the resulting commit list/order/messages and get explicit confirmation before touching history.

3. **Execute the rewrite via a non-interactive scripted rebase** - never hand-edit the interactive todo list live:
   - **Fold one commit into another (fixup/squash/reword), and that's the only change**: use `--autosquash` - it's simpler than `rewrite_range.py` for this exact case and does **not** require the two commits to be adjacent; it finds the `fixup!`/`squash!`/`amend!`-prefixed commit anywhere in the range and relocates it next to its target automatically.
   - **Fixup** (discard the new commit's message, keep the target's): `git commit --fixup=<target-SHA>`, then `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <base>` (or `--root` when the range includes the repo's first commit). Targeting is by commit identity/message markers, not by file path.
     - **Squash** (combine both messages, edited interactively): `git commit --squash=<target-SHA>`, then the same `--autosquash` rebase - this one *does* open an editor (to let you combine the two messages), unlike fixup.
     - **Reword** (replace the target's message with a new one, no content change): `git commit --fixup=reword:<target-SHA>` opens `$GIT_EDITOR` pre-filled with title `amend! <original subject>` plus the original body. A `GIT_EDITOR` script overwrites the body but **must preserve the `amend! <subject>` title line** (see Anti-patterns) - `--autosquash` matches on that prefix. Then the same `--autosquash` rebase.
     - If you're already staging new work with the intent to fold it into an existing unpushed commit, commit straight to `--fixup=`/`--squash=` instead of a plain commit followed by a separate fold step.
   - **Reorder, drop, or squash/fixup/reword combined with other reordering**: `--autosquash` cannot reorder or drop arbitrary commits, so use the plan-driven script instead:

     ```bash
     python3 "<base-dir>/rewrite_range.py" <plan.json> [base]
     ```

     The plan is a JSON array, oldest-first, giving the final desired top-to-bottom rebase order: `[{"sha": "...", "verb": "pick"}, {"sha": "...", "verb": "squash", "message": "final subject"}, ...]`. `verb` is one of `pick`/`drop`/`squash`/`fixup`/`reword`. `message` is optional and only meaningful on a `squash`/`reword` line - it sets the final subject for the commit that results from that block; omit it to keep git's default (concatenated) message. This one script replaces hand-written `GIT_SEQUENCE_EDITOR`/`GIT_EDITOR` shell scripts - never write those by hand.
      - **Critical plan semantics**: `squash` and `fixup` always fold into the nearest previous commit that is kept in the plan (typically the previous `pick`/`reword`). They are purely positional in the plan, never path-based.
      - **Preflight guard before executing `rewrite_range.py`**: identify topic boundaries first (for example feat/docs/fix groups) and ensure each `squash`/`fixup` line is immediately below the specific commit it should fold into. If the first commit of a topic block must keep its own identity, use `pick` or `reword` for that commit, then `fixup`/`squash` only subsequent commits in the same block.
      - **Sanity example**: to combine two docs commits while keeping an earlier feature commit separate, use `pick <feature>`, `reword <docs-1>`, `fixup <docs-2>` - never `pick <feature>`, `squash <docs-1>`.
   - On any conflict: resolve it properly, or `git rebase --abort` to restore history byte-identical to before the rebase started. Never `--skip`.

4. **Verify.** Build/test the project (follow `pre-implementation` and the project's build skill) before declaring done.

5. **Stop.** Report the new commit history to the user. Do not push - that is a separate, explicitly confirmed step.

## Anti-patterns

- Rewriting a commit that's already pushed.
- `--no-verify` on any commit/rebase step.
- `git rebase --skip` on conflict - silently drops that commit's changes.
- **Dropping the `amend! <subject>` title line** when overwriting a `--fixup=reword` message. `--autosquash` matches on that title prefix; if it's missing, the commit is silently left in place as its own separate commit with no error.
- Auto-pushing after a rewrite.
- Squashing or reordering commits that aren't actually related.
- Using `squash` on the first commit of a new topic block (for example docs after feat), which silently folds that topic into the prior commit.
- Attempting this on a range containing a merge commit - the safety gate blocks it; treat that as a separate, higher-risk task.
