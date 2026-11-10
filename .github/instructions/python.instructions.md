---
applyTo: "**/*.py"
excludeAgent: "cloud-agent"
---

# Python review

## Tests

- Put tests under `tests/` in files named `test_*.py`. pytest collects no other file.
- Isolate shared test state with an autouse fixture in `conftest.py`. Flag setup code copied into each test.
- llm-prompts runs tests in parallel with pytest-xdist. Flag a test that depends on run order or on state another test leaves.
- llm-prompts tests use fakes by default. Flag a new `real_io` or `real_prompts` mark where `fake_subprocess` or the small prompts tree covers the case.

## Types

- mypy runs strict. Flag a new `Any`, `cast()` or `# type: ignore` that a precise type would remove.

## Errors

- llm-prompts runs only ruff's default rules. Flag a new `except Exception` there that drops the error without a log line.

## Imports

- Keep slow imports, such as gitpython, off the hook startup path. Import them inside the function that needs them.

## cline-hooks

- Write a plugin's `on_hook()` as a chain of guard clauses that return early.

## mcp-memory

- Pass SQL values as `?` parameters. Interpolate only table and column names fixed in code. ruff's SQL check is off here.

## llm-prompts

- Read size thresholds from `src/llm_prompts/size_limits.py`. Flag a size number repeated in code, a test or a message.

## Example

Avoid:

```python
conn.query_one(f"SELECT id FROM entities WHERE name = '{name}'")
```

Prefer:

```python
conn.query_one("SELECT id FROM entities WHERE name = ?", (name,))
```
