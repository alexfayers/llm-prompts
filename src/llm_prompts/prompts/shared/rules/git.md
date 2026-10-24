---
roles: lead, worker, reviewer
---

# Git

- A logical change is one change that you could revert on its own, and the code would still work.
- Each logical change MUST be one commit. If one commit describes what another does, they are the SAME logical change and MUST be one commit, even across unrelated files.
- MUST fold a later edit to unpushed work into the commit of the logical change it belongs to, with `git commit --fixup=<sha>` plus an autosquash rebase, never `--amend`. See `git-usage` and `git-tidy`.
- A plan's commit split MUST NOT override that rule. MUST apply it to each planned commit and fold it into the matching commit with `--fixup=` if it fails.
- MUST rewrite only unpushed commits, per `git-usage`. MUST NOT use reorder, drop or reword merely to combine commits.
- MUST include at least one "Commit changes" item when building a {{TASK_PROGRESS}} checklist, and SHOULD add commit steps throughout it not only at the end.
- A PR SHOULD be one self-contained change, often one part of a feature, with its related tests.
- ~100 changed lines is usually fine and ~1000 usually too large. This is a guideline, not a target, and the reviewer decides.
- Many files make a change bigger. A deleted file or a trusted tool-generated refactor counts as small.
- Refactors SHOULD go in a separate PR.
- One logical change stays one commit.
