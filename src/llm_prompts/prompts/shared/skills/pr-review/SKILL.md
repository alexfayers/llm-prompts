---
name: pr-review
description: "Review pending changes against the repo's review instructions, or as a general senior developer. Use before pushing, opening a PR, or when asked to review the local diff."
---

# PR Review

## Scope

- MUST review uncommitted changes plus unpushed commits: `git -P diff HEAD` and `git -P diff @{u}..`.
- Without an upstream, MUST use the diff against the default branch.

## Rules

- MUST read each `.github/instructions/*.instructions.md` whose `applyTo` glob matches a changed path. `applyTo` holds comma-separated globs. MUST ignore `excludeAgent`.
- MUST check every changed matching path against the rules in its file.
- MUST check new files against `coding.md` layout rules.
- Without such files, MUST review as a senior developer: correctness, design, naming, edge cases, tests.

## Report

- MUST list findings by severity (high, medium, low), each with `path:line` and the rule file cited. A general finding cites no file.
- MUST NOT report style the repo's formatter or linter already enforces.
- MUST NOT report a finding without evidence in the diff or a new file.
- No findings: say so.
- MUST offer to fix the findings. MUST NOT fix before the user agrees.
