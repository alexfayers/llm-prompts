@_default: lint type-check test test-actions test-ts check

@_uv:
    uv -V 2> /dev/null || { echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'; exit 1;}

lint: _uv
    uv run ruff check --fix --show-fixes src/ tests/
    uv run ruff format src/ tests/

lint-check: _uv
    uv run ruff check src/ tests/

type-check: _uv
    uv run mypy src/ tests/

test: _uv
    uv run pytest -q --nf -n auto --maxprocesses 4 --dist worksteal --cov=. --cov-report=xml

test-actions:
    node --test .github/actions/*/*.test.js

test-ts:
    pnpm test-ts

check: _uv
    uv run llm-prompts check
