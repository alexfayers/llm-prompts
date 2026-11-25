---
name: pr-review
description: "Review pending changes against the repo's review instructions, and as a senior developer. Use before pushing, opening a PR, or when asked to review the local diff."
---

# PR Review

## Scope

- MUST run `python3 "{{SKILL_DIR}}/filter_findings.py" --scope`, and review all of its output: uncommitted changes, unpushed commits, the complete diff against the PR base and the default branch,
  and untracked paths.
- MUST read the contents of each untracked path.
- MUST also review the PR title and body where given.

## Rules

- MUST read each review rule file in the repo that matches a changed path. Example: `.github/instructions/*.instructions.md` whose `applyTo` comma-separated globs match. MUST ignore `excludeAgent`.
- MUST check every changed matching path against the rules in its file.
- MUST also follow the rules for each changed language, such as the Python rules, and the repo's own conventions.
- MUST always also review as a senior developer: correctness, design, naming, edge cases, tests.
- MUST push back hard on unnecessary changes and unnecessary tests, per the coding rules' smallest change: an unused extension point, local state a live check can replace,
  an unrequested CLI option or doc, more than one test per behaviour, or a test not through the public entry point.
- On your own diff before pushing, MUST first make those cuts, and check with `git diff --stat $(git merge-base <base> HEAD)` before and after that they shrank it.
  The no-apply rule below covers only the other findings.

## Report

- MUST give each finding a `severity`, `path:line`, and the rule file cited. A general finding cites no rule file.
- MUST run `python3 "{{SKILL_DIR}}/filter_findings.py" --help` for the severity scale.
- MUST pipe the findings as a JSON array through the script, and report only its output:

```bash
python3 "{{SKILL_DIR}}/filter_findings.py" <<'JSON'
[{"severity": 2, "path": "a.py:12", "rule": "...", "text": "..."}]
JSON
```

- MUST NOT report style the repo's formatter or linter already enforces.
- MUST NOT report a finding without evidence in the diff, a new file, or PR text.
- Output `[]`: say there are no findings.
- MUST suggest fixes for the findings. MUST NOT apply them.
- A review loop (review, fix, re-review) MUST follow `{{SKILL_DIR}}/review-loop.md`.
