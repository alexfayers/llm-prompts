---
audience: writer
roles: lead, worker, reviewer
---

# Git commits

- MUST fold a later edit to unpushed work into the commit of the logical change it belongs to, with `git commit --fixup=<sha>` plus an autosquash rebase, never `--amend`. See `git-usage`.
- A plan's commit split MUST NOT override that rule. MUST apply it to each planned commit and fold it into the matching commit with `--fixup=` if it fails.
- MUST rewrite only unpushed commits, per `git-usage`. MUST NOT use reorder, drop or reword merely to combine commits.
- MUST include at least one "Commit changes" item when building a {{TASK_PROGRESS}} checklist, and SHOULD add commit steps throughout it not only at the end.
- In a batch or multi-delegate run, the lead MUST bundle finished changes into one PR per related area, within the PR size guideline - MUST NOT open one per delegate or pick.
  MUST stay within the in-flight review limit (`max_in_flight` under `[reviews]` in llm-prompts' `config.toml`) and raise it only on the user's direction.
- MUST merge PRs in dependency order: a base PR before the PRs that build on it.
