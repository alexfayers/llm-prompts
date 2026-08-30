---
description: Python-specific coding guidelines
paths: '**/*.py'
---

# Python coding guidelines

Unless otherwise specified, these MUST apply:

- Type hints MUST be used for functions/methods, and for initialization of empty collections (lists, sets, etc)
- Google style docstrings MUST give a brief summary of functions and methods
- ruff for linting and formatting (run with `--fix` first), but only where the project uses ruff. Many packages use black + isort or flake8 instead - MUST check `pyproject.toml`/`setup.cfg` for `[tool.black]`, `[tool.isort]`, `[tool.ruff]`, or a flake8 config BEFORE running any formatter. Running ruff on a black/isort project makes invasive unrelated changes (e.g. `from __future__ import annotations`, `TYPE_CHECKING` blocks). MUST match the project's existing toolchain.
- mypy for type checking
- pytest for testing
- object oriented approach, one class per file unless classes are closely related (a small type stub MAY share a file with another class)
- follow SOLID principles
- keep code loosely decoupled - SHOULD NOT over engineer with middleware unless it makes sense, but SHOULD follow single responsibility where possible
- within tests, pytest fixtures SHOULD refactor out repeated code
- argparse SHOULD be used for command line argument parsing, with a function for building the parser and a function for doing the parsing and starting the program.
- MUST NOT catch an exception and do nothing with it
- When catching exceptions, the try block MUST contain only the code that could raise.
- MUST NOT return raw exception text (`str(e)`, stack traces) to an external caller (API response, HTTP body). It can leak internal detail (table names, ARNs, hostnames, file paths). MUST log full detail server-side and return a generic message (e.g. "Internal server error"). Hand-built, input-derived messages (e.g. "Resolver group 'X' already subscribed") are fine.
- Imports MUST be at the top of the file.
- SHOULD NOT use the `Any` type - only as a last resort or if explicitly told otherwise.
- MUST NOT annotate with `object` - use a precise type, or `Any` where you genuinely cannot.
- For external tool interactions, SHOULD research and prefer a library (e.g. `gitpython` for git) - MUST use `subprocess` only where no suitable library exists.
