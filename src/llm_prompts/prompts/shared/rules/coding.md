---
description: Coding guidelines to follow when generating, reviewing, or modifying code
copilot_apply_to: '**'
---

# Coding guidelines

- MUST keep code concise but readable, and any change minimal.
- Code MUST be self-documenting with descriptive names and minimal comments. MUST NOT add a comment that refers to the change you are making or explains why - comments describe the code, only where genuinely complex.
- MUST add new imports at THE SAME TIME as the code that uses them.
- Produced code MUST follow the existing style within the package.
- MUST NOT {{TOOL_COMPLETE}} until all tasks in the focus chain are done.
- {{ACTION_NO_NARRATE}}
- MUST write for reuse: where several functions do similar things, merge them or create an interface.
- Committed text (docs, CLAUDE.md, design decisions) MUST describe the current atomic state - never a failed intermediate approach, a removed feature, or "we tried X then switched to Y".
- SHOULD NOT add a variable assignment that does not improve clarity; a value used once needs no name.
- SHOULD NOT use magic numbers: where a threshold recurs, derive every occurrence from one named constant.
- MUST leave code better than you found it - fix an issue you notice in code you are already editing. This stops at the ownership boundary: MUST NOT edit another team's or package's code just because your change sits next to it. Raise the rest separately.
- When fixing a bug, fix ALL directly related issues in the same code path - MUST NOT dismiss a pre-existing failure as separate if it shares root cause or context.
- Before adding a parameter to a signature, MUST verify the body uses it.
- Before declaring a value or function dead, MUST search the WHOLE workspace - a value can be set in one package and consumed in a sibling.
- After fixing an error you wrote, MUST record the mistake and fix as a memory observation.
- MUST NOT use non-ascii characters (e.g. emdash); use the ascii equivalent.
- In committed files, MUST NOT name specific collaborators or hardcode user-specific values (aliases, account IDs, stack names) - use a placeholder like `<account-id>`.
- In a globally-distributed instruction or doc, MUST NOT assert behaviour depending on the reader's local config ("this command is auto-approved"). State the action, not the local consequence.
- Before writing new tooling to check something, MUST check whether an existing tool already does it.

# Testing guidelines

- Before EVERY commit and push, and before marking any task complete or submitting a CR, you MUST build the package and confirm all tests pass. An earlier passing run does NOT carry over - re-run the full suite immediately before the git operation.
- MUST verify with the project's real configuration, not a stricter one you chose - read the build/CI config for the flags actually used, and compare against the committed baseline before calling something a regression.
- When fixing a REPORTED bug, MUST reproduce the symptom with a harness matching how the code is actually invoked, then confirm the fix makes that reproduction pass. A test with unrealistic inputs can pass while the real bug is untouched. Where you cannot reproduce it, MUST say so and keep investigating - MUST NOT ship a speculative fix and claim it resolved.
- MUST verify an integration feature against the real target, not just a stub. MUST probe read-only first (`--dry-run`, `stat` before and after), then run the real path, and state which parts were stub-tested.
- Tests MUST run through the project's standard build/test invocation, never a bespoke script outside it, or they stop being part of the normal gate.
- For any change that adds or repositions UI, you MUST render the page and look at it before claiming done - an API test verifies data, not appearance. Where a plan flagged a layout risk, MUST resolve it in the design rather than defer.
- Before running tests, a test MUST exist for the expected behaviour.
- When delegating test-writing, MUST state that the motivating real-world case stays out of the suite, or the delegate hardcodes it.
