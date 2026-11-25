# Review prompt

Pass this to the reviewer with the content to review.

## Bar

- MUST report only: real bugs, data loss, missing tests for new behaviour, PR text that does not match the diff, and needless code.
- MUST NOT report style nits.
- A reviewer delegate MUST load the repo's `.github/instructions/review.instructions.md`, where present, and hold to its Severity bar.

## Loading the diff

- MUST load the diff with `gh pr diff <n>` or `git diff <range>`, never a web fetch.

## Output

- MUST return numbered findings, each with `file:line`, a severity (high, medium, low) and a one-line fix.
- A reviewer following `SKILL.md` MUST render `filter_findings.py`'s output: `[]` as `CLEAN`, each other item as one numbered finding.
- With no findings, the report body MUST be only `CLEAN`. A caller that needs its own reply format (e.g. an OUTCOME line) MUST wrap that body, not replace it.

## Stop rule

- The caller MUST discard low-severity findings.
- The fixer MAY push back on a finding below the bar, with the reason, instead of fixing it.
- Where findings repeat a root cause, the fixer MUST state the feature's invariant in one line, enforce it in one place by construction,
  and delete the per-path special cases, not patch each instance.
- The caller MUST stop the review loop after 5 fix rounds, or once only edge cases remain.
- MUST add the `owner-reviewed` label, or approve, only after a review of the current head comes back CLEAN.
  Reaching the fix-round limit is not a pass: MUST review again, and if it is still not CLEAN, report to the user.
