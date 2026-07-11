---
description: Stop and ask for help when a task or tool fails
copilot_apply_to: '**'
---

# Stop On Failures

If you cannot run a task or tool, such as in the following situations:
- Failed build
- Failed tool call
- Failed command
- Missing info

Unless you can immediately fix the issue, **do not proceed**. **Ask the user for help!**

Do not skip or alter tasks or take a different approach without explicit user permission.

**Never** dismiss warnings as "expected" without verifying the cause. If a warning appears after your change, assume you caused it and investigate immediately.

**Never** dismiss a failing test/check as "pre-existing" or "not from my change" without proving it against the baseline. "Pre-existing relative to my latest commits" is not the same as "pre-existing on the main branch" - a working branch can carry a regression from an earlier branch-only commit that no CI ever exercised. Before asserting pre-existing: diff the artifact/config the failure depends on between the branch and the main branch, and confirm the failure reproduces on the main branch (e.g. `git merge-base --is-ancestor <suspect-commit> origin/main`). If CI never ran the check (a disabled or broken CI lane, an unpushed branch, a locally-skipped platform), treat the local failure as unproven and trace it - a coverage gap lets a real regression masquerade as benign.
