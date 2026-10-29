---
roles: lead, reasoner, worker, reviewer
description: Coding guidelines to follow when generating, reviewing, or modifying code
---

# Coding guidelines

- MUST keep code concise but readable, and any change minimal.
- A size limit (lines, words) is a ceiling, never a target. MUST make the smallest change that delivers the behaviour and remove redundant code.
- Code MUST be self-documenting with descriptive names and minimal comments. MUST NOT add a comment that refers to the change you are making, explains why, or names other code that uses it - comments describe the code, only where genuinely complex.
- MUST add new imports at THE SAME TIME as the code that uses them.
- When a change adds, or newly requires, an environment variable, config key or setting, MUST update every doc, template and manifest that lists it in the SAME change.
- Produced code MUST follow the existing style within the package.
- MUST NOT {{TOOL_COMPLETE}} until all tasks in the focus chain are done.
- {{ACTION_NO_NARRATE}}
- MUST write for reuse: merge similar functions or create an interface.
- MUST make a change once, at its source, not at each place that uses it. SHOULD keep one source of truth per value and derive the rest from it at use time - never copy it into state that must be kept in sync.
- MUST NOT change code the task does not need; leaving code better applies only to code you are already editing.
- Committed text (docs, CLAUDE.md, design decisions) MUST describe the current state - never a failed approach, a removed feature, or "we tried X then switched to Y".
- SHOULD NOT assign a variable that adds no clarity; a value used once needs no name.
- SHOULD NOT use magic numbers: where a threshold recurs, derive every occurrence from one named constant.
- MUST leave code better than you found it - fix an issue you notice in code you are already editing. MUST NOT edit another team's or package's code just because your change sits next to it. Raise the rest separately.
- When fixing a bug, fix ALL directly related issues in the same code path - MUST NOT dismiss a pre-existing failure that shares its root cause or context.
- Before adding a parameter to a signature, MUST verify the body uses it.
- Before declaring a value or function dead, MUST search the WHOLE workspace.
- After fixing an error you wrote, MUST record the mistake and fix as a memory observation.
- MUST NOT use non-ascii characters (e.g. emdash); use ascii equivalents.
- In committed files, MUST NOT name collaborators or hardcode user-specific values (aliases, account IDs, stack names) - use a placeholder like `<account-id>`.
- In a globally-distributed instruction or doc, MUST NOT assert behaviour depending on the reader's local config ("this command is auto-approved"). State the action, not the consequence.
- Before writing tooling to check something, MUST check whether an existing tool does it.
- SHOULD NOT limit parallelization in code for hardware limits - the OS/runtime scheduler is the cap.

# Testing guidelines

- Before EVERY commit and push, and before marking any task complete or submitting a CR, you MUST build the package and confirm all tests pass. An earlier run does NOT carry over - re-run the full suite immediately before the git operation.
- MUST verify with the project's real configuration, not a stricter one you chose - read the build/CI config for the flags used, and compare against the committed baseline before calling something a regression.
- When fixing a REPORTED bug, MUST reproduce the symptom with a harness matching how the code is actually invoked, then confirm the fix makes that reproduction pass. Where you cannot reproduce it, MUST say so and keep investigating - MUST NOT ship a speculative fix and claim it resolved.
- MUST verify an integration feature against the real target, not just a stub. MUST probe read-only first (`--dry-run`, `stat` before and after), then run the real path, and state which parts were stub-tested.
- Tests MUST run through the project's standard build/test invocation, never a bespoke script outside it.
- For any change that adds or repositions UI, you MUST render the page and look at it before claiming done. Where a plan flagged a layout risk, MUST resolve it in the design rather than defer.
- MUST add tests only for new behaviour or a reported bug. A refactor MUST rely on existing tests. If no test covers the refactored code, MUST add one test through its public entry point.
- When delegating test-writing, MUST state that the motivating real-world case stays out of the suite.
- MUST NOT predict a runnable tool's output (linter, formatter, type checker, tests, compiler, `--help`) - run it and read the result.
