---
description: Guidelines for writing and changing tests
paths: '**/test_*.py, **/conftest.py, **/*_test.*, **/*.test.*, **/*.spec.*, **/tests/**, **/test/**'
---

# Test authoring guidelines

- SHOULD exercise real code paths and avoid mocks where a real path is feasible - reserve mocking for what is genuinely infeasible in-process (a live network call, a rate-limited API, a destructive side effect).
- Tests cover our code only - MUST NOT test a built-in or external library.
- Test behaviour, not syntax; e.g. do not test that a config has specific defaults.
- MUST NOT duplicate behaviour in a test definition - always test the live code.
- MUST NOT couple a test to dynamic external state (live service status, registries, dates) - derive expectations from the same source of truth the code reads, and assert the invariant, not a snapshot.
- Keep the real-world case that motivated a change OUT of the test suite - reproduce it with a generic synthetic fixture the test builds itself (neutral names, a temp directory).
