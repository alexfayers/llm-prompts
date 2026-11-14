---
name: pr-review
description: "Review pending changes against the repo's review instructions, and as a senior developer. Use before pushing, opening a PR, or when asked to review the local diff."
---

# PR Review

## Scope

- MUST review uncommitted changes plus unpushed commits: `git -P diff HEAD` and `git -P diff @{u}..`, or the diff against the default branch without an upstream. MUST also review the complete diff against the PR base.
- MUST also review the PR title and body where given.
- MUST also list untracked paths with `git -P status --porcelain` and review their contents.

## Rules

- MUST read each review rule file in the repo that matches a changed path. Example: `.github/instructions/*.instructions.md` whose `applyTo` comma-separated globs match. MUST ignore `excludeAgent`.
- MUST check every changed matching path against the rules in its file.
- MUST also follow the rules for each changed language, such as the Python rules, and the repo's own conventions.
- MUST always also review as a senior developer: correctness, design, naming, edge cases, tests.
- MUST push back hard on unnecessary changes and unnecessary tests.

## Report

- MUST give each finding a `severity`, `path:line`, and the rule file cited. A general finding cites no rule file.
- MUST run `python3 "<base-dir>/filter_findings.py" --help` for the severity scale.
- MUST pipe the findings as a JSON array through the script, and report only its output:

```bash
python3 "<base-dir>/filter_findings.py" <<'JSON'
[{"severity": 2, "path": "a.py:12", "rule": "...", "text": "..."}]
JSON
```

- MUST NOT report style the repo's formatter or linter already enforces.
- MUST NOT report a finding without evidence in the diff, a new file, or PR text.
- Output `[]`: say there are no findings.
- MUST offer to fix the findings. MUST NOT fix before the user agrees, unless the invoking workflow says to fix findings.
