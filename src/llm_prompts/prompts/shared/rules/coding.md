---
roles: lead, reasoner, worker, reviewer
description: Coding guidelines to follow when generating, reviewing, or modifying code
---

# Coding guidelines

- MUST keep code concise but readable. MUST treat size limits as ceilings, not targets. MUST make the smallest change that delivers the behaviour, remove redundant code, and fix every caller,
  test and fixture it breaks.
- MUST pick the first option in this list that fully works:
  1. Use what the codebase already has, as nearby code does.
  2. Use the standard library or platform, unless the project has its own.
  3. Use an installed dependency. MUST NOT add a new one for a few lines.
  4. Write it as one readable line of code.
  5. Write new code.
- MUST NOT cut trust-boundary validation, data-loss error handling, security or accessibility.
- Code MUST be self-documenting with descriptive names. Comments MUST describe the code. Add a comment only where the code is genuinely complex,
  or to mark a known limit as `shortcut: <limit>, <when to upgrade>`. A comment MUST NOT describe the change, its reason, or code that uses it.
- MUST add new imports in the SAME edit as the code using them.
- When a change adds, or newly requires, an environment variable, config key or setting, MUST update every doc, template and manifest that lists it in the SAME change.
- Code MUST follow the package's existing style.
- Before a new related file takes a non-root folder from 7 to 8 files, SHOULD put it in an existing or new short-named area subfolder (`<area>/<part>`,
  not `<area>_<part>`), unless a tool requires a flat layout. MUST NOT regroup existing files unasked.
- MUST NOT {{TOOL_COMPLETE}} until all tasks in the focus chain are done.
- {{ACTION_NO_NARRATE}}
- MUST write for reuse: merge similar functions or add an interface.
- MUST make a change once, at its source, not at each place that uses it. SHOULD keep one source of truth per value, deriving the rest at use time, never copying it into state kept in sync.
- Committed text (docs, CLAUDE.md, PR bodies, design decisions) MUST describe only the current state and what the code does, never a failed approach or removed feature.
- SHOULD NOT assign a variable that adds no clarity. A value used once needs no name.
- SHOULD NOT use magic numbers: where a threshold recurs, derive each use from one named constant.
- MUST NOT change code the task doesn't need. MUST fix issues you notice in code you already edit.
  MUST NOT edit another team's or package's code just because yours sits next to it. Raise the rest separately.
- When fixing a bug, MUST fix ALL related issues in its code path, and MUST NOT dismiss a pre-existing failure with the same root cause or context.
- Before adding a parameter to a signature, MUST verify the body uses it.
- Before declaring code dead, MUST search the WHOLE workspace.
- After fixing an error you wrote, MUST record the mistake and fix in memory - a delegate reports it instead.
- MUST NOT use non-ascii characters (e.g. emdash).
- In committed files, MUST NOT name collaborators or hardcode user-specific values (aliases, account IDs, stack names) - use a placeholder (`<account-id>`).
- In a globally-distributed instruction or doc, MUST state the action. MUST NOT state behaviour that depends on the reader's local config ("this command is auto-approved").
- Before writing a checking tool, MUST check whether one exists.
- SHOULD NOT cap parallelism in code for hardware. The OS or runtime scheduler caps it.

# Testing guidelines

- Before EVERY commit, push, CR or task completion, MUST build and run the full suite to a pass. An earlier run does NOT count.
- MUST verify through the project's standard build/test command, with its real CI config and flags. MUST NOT use a bespoke script or a stricter config you chose.
  MUST compare against the committed baseline before calling something a regression.
- When fixing a REPORTED bug, MUST reproduce the symptom with a harness matching how the code runs, then confirm the fix makes it pass.
  If you cannot reproduce it, MUST say so and keep investigating. MUST NOT ship a speculative fix and claim it resolved.
- MUST verify an integration feature against the real target, not just a stub. MUST probe read-only first (--dry-run, stat before and after), run the real path, and name the stub-tested parts.
- For a change that adds or moves UI, MUST render the page and look at it before claiming done. MUST resolve a plan-flagged layout risk in the design, not defer it.
- MUST add tests only for new behaviour or a reported bug. A refactor MUST rely on existing tests. If none covers it, MUST add one test through its public entry point.
  MUST decline a reviewer's test request that conflicts with these rules, and say why.
- When delegating test-writing, MUST say the motivating real-world case stays out of the suite.
- MUST NOT predict a runnable tool's output (linter, type checker, tests, --help) - run it and read it.
