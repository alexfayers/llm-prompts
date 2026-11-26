ts_test_heap_mb := "4096"
ts_test_timeout_seconds := "900"

@_default: lint _checks

[parallel]
_checks: type-check type-check-ts test test-ts check

@_uv:
    uv -V 2> /dev/null || { echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'; exit 1;}

lint: _uv
    uv run ruff check --fix --show-fixes src/ tests/
    uv run ruff format src/ tests/

lint-check: _uv
    uv run ruff check src/ tests/

type-check: _uv
    uv run mypy src/ tests/

@_pnpm:
    pnpm install --frozen-lockfile

type-check-ts: _pnpm
    pnpm type-check

test: _uv
    uv run pytest -q --nf -n auto --maxprocesses 4 --dist worksteal --cov=. --cov-report=xml

test-ts: _pnpm
    NODE_OPTIONS=--max-old-space-size={{ts_test_heap_mb}} node tests/ts/run-with-timeout.mjs {{ts_test_timeout_seconds}} node --test --experimental-test-module-mocks tests/ts/*.test.ts

check: _uv
    uv run llm-prompts check
