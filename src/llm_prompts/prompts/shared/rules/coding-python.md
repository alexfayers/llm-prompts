---
description: Python-specific coding guidelines
copilot_apply_to: '**'
kiro_inclusion: fileMatch
kiro_file_match_pattern: '**/*.py'
---

# Python coding guidelines

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
- Never annotate with `object`. Prefer a precise type; if you genuinely cannot, use `Any` rather than `object`.
- Before using `subprocess` for external tool interactions, research and prefer a library (e.g. `gitpython` for git operations). Only use `subprocess` when no suitable library exists.
