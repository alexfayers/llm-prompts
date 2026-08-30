# Git

- MUST include at least one "Commit changes" item when building a {{TASK_PROGRESS}} checklist, and SHOULD add commit steps throughout it rather than only at the end - committing often is what keeps work saved.
- Each logical change is ONE commit. Keep that true as you go: fold each new piece into the commit it belongs to rather than piling up ten commits for one feature and squashing at the end.
- Test: if one commit describes what another commit does, they are the SAME logical change and MUST be one commit, even across unrelated files - splitting leaves the description stale against the commit it describes.
- `git commit --amend` reaches HEAD only; for an earlier unpushed commit use `git commit --fixup=<sha>` plus an autosquash rebase. See the `git-usage` and `git-tidy` skills for the exact commands.
- Amending and fixup apply ONLY to unpushed commits. `git-tidy`'s bigger reshapes - reorder, drop, reword - are for when that is genuinely what you need, not the normal route to one commit.
