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

Unless you can immediately fix the issue, **MUST NOT proceed**. **MUST ask the user for help.**

**A call that failed because its target was not in the state you assumed cannot succeed on a blind retry.** When an edit's match text is not found or not unique, or a write throws because the entity, observation, or relation does not exist, MUST re-read that exact target first and reissue from what the read returned - MUST NOT guess a variation of the same call.

MUST NOT skip or alter tasks or take a different approach without explicit user permission.

**MUST NOT** dismiss warnings as "expected" without verifying the cause. If a warning appears after your change, MUST assume you caused it and investigate immediately.

**MUST NOT** dismiss a failing test/check as "pre-existing" or "not from my change" without either fixing it or checking with the user. "Pre-existing relative to my latest commits" is not the same as "pre-existing on the main branch" - a working branch can carry a regression from an earlier branch-only commit that no CI ever exercised, so you cannot tell from the branch alone whether it's really pre-existing.

If the failure is easily fixable, MUST just fix it - that's faster than proving whose fault it is. Only if it's not easily fixable (the fix is unclear, or it depends on something outside this change) SHOULD you stop and ask the user, rather than asserting it's pre-existing and moving on unproven.

Once a specific tool/MCP call is confirmed to leak or expose sensitive data (secrets, credentials, PII), MUST pause and ask - or use a narrower non-leaking alternative - before calling it again.
