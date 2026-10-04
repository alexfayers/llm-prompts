---
description: Guidelines for writing and changing tests
paths: '**/test_*.py, **/conftest.py, **/*_test.*, **/*.test.*, **/*.spec.*, **/tests/**, **/test/**'
---

# Test authoring guidelines

- Unit tests SHOULD mock at system boundaries: the filesystem, subprocesses, git, the network, the clock, external services and third-party libraries. They then exercise only our own logic.
- Integration tests MUST use the real dependencies.
- MAY use the real thing where a mock costs more than it buys. MAY also use it where the project's existing tests do not mock, to match them.
- MUST NOT mock our own modules.
- Tests cover our code only - MUST NOT test a built-in or external library.
- Test behaviour, not syntax; e.g. do not test that a config has specific defaults.
- MUST NOT duplicate behaviour in a test definition - always test the live code.
- MUST NOT couple a test to dynamic external state (live service status, registries, dates) - derive expectations from the same source of truth the code reads, and assert the invariant, not a snapshot.
- Keep the real-world case that motivated a change OUT of the test suite - reproduce it with a generic synthetic fixture the test builds itself (neutral names, a temp directory).
- MUST extend existing tests or patterns where they exist, rather than writing new ones.
