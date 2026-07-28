---
description: Coding guidelines to follow when generating, reviewing, or modifying code
copilot_apply_to: '**'
---

# Coding guidelines

- Keep any resulting code concise but readable
- Any changes to code must be minimal
- Code must be self-documenting with minimal comments
  - NEVER add comments that refer to the changes you are making. Comments must only refer to the code and implementation itself.
  - Variable/function/method names must be descriptive
  - Comments should not be necessary in general
- Add new imports at THE SAME TIME as making code changes
- All produced code MUST follow the existing style within the package (variable names, documentation, etc.)
- NEVER {{TOOL_COMPLETE}} until all tasks in the focus chain are completed.
- {{ACTION_NO_NARRATE}}
- Code should be written with reusability and maintainability in mind at all times. If multiple functions do similar things, merge them into one or create an interface
- It is extremely important that you NEVER write comments explaining the reasoning for a specific change. Comments should only be used to explain complex code. If comments are required, consider a different approach.
- Committed text (docs, CLAUDE.md, design decisions) must describe the current atomic state. Never reference failed intermediate approaches, removed features, or "we tried X then switched to Y". The code is the source of truth for what exists now.
- Avoid unnecessary variable assignment unless it improves the clarity of the code. If a variable is used once, it probably doesn't need to be a variable.
- Leave code better than you found it. If you notice an issue with something that you are already editing, fix it!
- When fixing a bug, investigate and fix ALL directly related issues in the same code path - do not dismiss pre-existing failures as "separate" if they share root cause or context with the current fix.
- Before adding a parameter to a function signature, verify it is actually used in the function body. Remove unused parameters.
- If you write code that contains an error and subsequently fix it, record the mistake and fix as a memory observation so the same error is not repeated in future sessions.
- When writing any text, NEVER use non-ascii characters such as emdash (`—`). Always use equivalent ascii characters, like `-`.
- In committed files (docs, CLAUDE.md, config), never reference specific collaborators by name. Use generic terms ("collaborators", "team members", "other agents") instead.
- Never hardcode user-specific values (aliases, personal account IDs, personal stack names) in committed files. Always use generic placeholders like `<personal-stack-id>`, `<account-id>`, `<profile>`.
- In a globally-distributed instruction/doc (rules, skills, shared templates), never assert behaviour that depends on the individual reader's local configuration - e.g. "this command is auto-approved", "this needs no confirmation", "the tool is on PATH". Auto-approval hinges on the reader's own permission allowlist; availability hinges on their install. State the action to take; leave the local-environment consequence out.
- Before writing new code/tooling to check or verify something, check whether an existing tool already does it - prefer that over building new.

# Testing guidelines

- **CRITICAL: Before EVERY commit and push, and before marking any task complete or submitting a CR, you MUST build the package and confirm all tests pass.** This is non-negotiable. A green build is a hard prerequisite - never skip it, never assume it passes, never defer it. A passing run earlier in the session does NOT carry over: any change since then (including a docs/TODO-only follow-up commit) requires re-running the full suite before the next commit or push. Re-run immediately before the git operation, not once at the start.
- **Verify with the project's real configuration, not a stricter one you chose.** Read the build/CI config for the flags actually used before deciding what "passing" means; enabling stricter checks than the project uses surfaces pre-existing issues that look like new regressions but are out of scope. Be wary of a stale/incremental verification baseline: only re-processed inputs are re-checked, so a "clean" incremental run does not prove a new setting passes across the whole tree. When something looks like a regression, compare against the committed baseline to confirm it is not pre-existing.
- **When fixing a REPORTED bug (a freeze, crash, wrong output), first reproduce the symptom with a harness that matches how the code is actually invoked - then confirm your fix makes that reproduction pass.** A benchmark or test that exercises a function with unrealistic inputs (e.g. a `nullptr`/no-op callback where production wires a real one, an empty config, a tiny fixture) can pass while the real bug is untouched - a structural blind spot that makes you "fix" latent issues that were never the reported problem. Mirror the real call site's parameters and wiring. If you cannot reproduce the symptom, say so and keep investigating; do not ship speculative fixes and claim the issue is resolved.
- **Verify an integration feature against the real target, not just a stub.** A feature whose job is to talk to an external target (host, API, DB) needs a real exercise - a mock only tests control-flow and misses real-world mismatches (wrong path, a destructive overwrite, an auth gap). Probe the target read-only first (reachability, fingerprint/version compare, `--dry-run`, `stat` before/after), which also surfaces footguns cheaply, then run the real path. Distinguish stub-tested from really-run when reporting.
- **Default to exercising real code paths in test construction; avoid mocks where a real path is feasible.** Reserve mocking for what is genuinely infeasible to run for real in the test process (a live network call, a paid/rate-limited external API, a destructive side effect). If a dependency is safe to invoke for real (pure in-process logic, a bundled offline data snapshot, a local file read), invoke it for real rather than mocking it for convenience or isolation - a mock only proves the mock's contract, not the real one.
- **Tests must run through the project's standard build/test invocation**, never a bespoke ad-hoc script or runner outside that path - otherwise the test suite silently stops being part of what CI/the team's normal gate actually checks.
- **For any change that adds or repositions UI (CSS, fixed-position elements, form controls, layout), you MUST render the page and look at it before claiming done.** An API/curl test verifies data, not appearance - it will not catch overlap, an unstyled control, or clashing copy. Render the populated/interactive state (headless Chrome via CDP if needed) and visually confirm. If a plan flagged a layout/overlap risk, resolve it in the design - never ship the flagged position and defer.
- Before running tests, always ensure that there are tests that check for the expected behavior
- Tests should only cover our code. Do not test the functionality of built-in or external libraries.
- Test behavior, not syntax. For example, do not test that a config has specific defaults set.
- Never duplicate behavior in the test definition - always test the live code.
- Do not couple tests to dynamic external state (e.g. live service status, environment registries, current dates, resource inventories). Derive expectations from the same source-of-truth the code under test reads, so the test tracks that state automatically. A test that must be hand-edited whenever external data changes (a hardcoded list, a snapshot of "what exists today") is brittle - assert the behaviour/invariant, not the current snapshot.
