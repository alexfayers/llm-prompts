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

## Python

Unless otherwise specified:

- Type hints must be used for functions/methods, and for the initialization of empty collections (lists, sets, etc)
- Google style docstrings must be used to give a brief summary of functions and methods
- ruff for linting and formatting (run with `--fix` first), BUT only after confirming the project uses ruff. Many packages use black + isort or flake8 instead - check `pyproject.toml`/`setup.cfg` for `[tool.black]`, `[tool.isort]`, `[tool.ruff]`, or a flake8 config BEFORE running any formatter. Running ruff on a black/isort project makes invasive unrelated changes (e.g. `from __future__ import annotations`, `TYPE_CHECKING` blocks). Match the project's existing toolchain.
- mypy for type checking
- pytest for testing
- object oriented approach, one class per file unless classes are closely related (a small type stub is allowed in a file with another class, for example)
- follow SOLID principles
- keep code loosely decoupled - don't over engineer with middleware unless it makes sense, but follow single responsibility where possible
- within tests, pytest fixtures should be used to refactor out repeated code
- argparse should be used for command line argument parsing, with a function for building the parser and a function for doing the parsing and starting the program. This makes integrating testing easier later.
- Never catch an exception and do nothing with it
- When catching exceptions, only put the code that could raise the exception(s) in the try block.
- Never return raw exception text (`str(e)`, stack traces) to an external caller (API response, HTTP body). It can leak internal detail (table names, ARNs, hostnames, file paths). Log the full detail server-side and return a generic message (e.g. "Internal server error") to the client. Hand-built, input-derived messages (e.g. "Resolver group 'X' already subscribed") are fine.
- Imports **must** always be at the top of the file.
- Avoid using the `Any` type wherever possible. Use it only as a last resort or if explicitly told otherwise.
- Before using `subprocess` for external tool interactions, research and prefer a library (e.g. `gitpython` for git operations). Only use `subprocess` when no suitable library exists.

## Shell

- NEVER use the `-f` flag with the `rm` command. It is too high risk.
- NEVER use `rm -rf`. Use `rm -r` instead.
- NEVER kill processes by port number (e.g. `kill $(lsof -ti:PORT)`). This can kill unrelated processes (e.g. VS Code extensions). Always kill by specific PID instead.

# Testing guidelines

- **CRITICAL: Before marking any task as complete or submitting a CR, you MUST build the package and confirm all tests pass.** This is non-negotiable. A green build is a hard prerequisite - never skip it, never assume it passes, never defer it.
- **For any change that adds or repositions UI (CSS, fixed-position elements, form controls, layout), you MUST render the page and look at it before claiming done.** An API/curl test verifies data, not appearance - it will not catch overlap, an unstyled control, or clashing copy. Render the populated/interactive state (headless Chrome via CDP if needed) and visually confirm. If a plan flagged a layout/overlap risk, resolve it in the design - never ship the flagged position and defer.
- Before running tests, always ensure that there are tests that check for the expected behavior
- Tests should only cover our code. Do not test the functionality of built-in or external libraries.
- Test behavior, not syntax. For example, do not test that a config has specific defaults set.
- Never duplicate behavior in the test definition - always test the live code.
- Do not couple tests to dynamic external state (e.g. live service status, environment registries, current dates, resource inventories). Derive expectations from the same source-of-truth the code under test reads, so the test tracks that state automatically. A test that must be hand-edited whenever external data changes (a hardcoded list, a snapshot of "what exists today") is brittle - assert the behaviour/invariant, not the current snapshot.
