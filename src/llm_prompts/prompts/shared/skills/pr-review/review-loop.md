# Review prompt

Pass this to the reviewer with the content to review.

## Bar

- MUST report only: real bugs, data loss, missing tests for new behaviour, PR text that does not match the diff, and needless code.
- MUST NOT report style nits.
- MUST rate each finding's likelihood in real use (likely, rare) as well as its severity.
- MUST block only on a finding that is likely in real use, or that loses data or exposes a secret in a normal setup.
  A rare edge case (a hostile setup, a crash at one exact step, a narrow race) that loses no data and exposes no secret MUST NOT be a numbered finding.
  The reviewer MUST list it on the `DEFERRED:` line, tagged `rare`. The fixer MAY leave it as a `shortcut:` comment.
- A reviewer delegate MUST load the repo's `.github/instructions/review.instructions.md`, where present, and hold to its Severity bar.

## Re-review rounds

- A re-reviewer MUST check that each earlier finding is fixed, and look for regressions in the lines the fix touched.
- After round 2, a re-reviewer MUST check only the earlier findings and any new code they caused to fail. It MUST NOT look for new problems.
- A re-reviewer MUST report a new finding in untouched code only when it is high.
- A medium finding in untouched code MUST NOT block `CLEAN`. The reviewer MUST list it on the `DEFERRED:` line.
  The caller MUST file each one not tagged `rare` as a follow-up issue.

## Loading the diff

- MUST load the diff with `gh pr diff <n>` or `git diff <range>`, never a web fetch.

## Output

- MUST return numbered findings, each with `file:line`, a severity (high, medium, low), a likelihood and a one-line fix.
- A reviewer following `SKILL.md` MUST render `filter_findings.py`'s output: `[]` as `CLEAN`, each other item as one numbered finding.
- With no findings, the report body MUST be only `CLEAN`, plus any `DEFERRED:` line.
- A report MAY end with one `DEFERRED:` line listing deferred findings, after `CLEAN` or after the numbered findings.
- A caller that needs its own reply format (e.g. an OUTCOME line) MUST wrap that body, not replace it.

## Stop rule

- The caller MUST discard low-severity findings.
- The fixer MAY push back on a finding below the bar, with the reason, instead of fixing it.
- Where findings repeat a root cause, the fixer MUST state the feature's invariant in one line, enforce it in one place by construction,
  and delete the per-path special cases, not patch each instance.
- Where a fix would add new state (a file, a lock or a journal), the fixer MUST first try a simpler design that removes the problem.
- The caller MUST stop the review loop after 5 fix rounds, or once only edge cases remain.
{% if AGENT == "pi" %}
- Where a suitable warm fork exists and costs less than starting fresh, a fix round MUST resume the PR's writer, a re-review MUST resume the PR's last reviewer,
  with `fork_resume`, and new parallel reviews MUST branch with `from` a finished brief, per `delegation.md`'s warm-fork rule. Otherwise start a fresh fork.
{% endif %}
- MUST add the `owner-reviewed` label, or approve, only after a review of the current head comes back CLEAN.
  Reaching the fix-round limit is not a pass: MUST review again, and if it is still not CLEAN, escalate to the user.
