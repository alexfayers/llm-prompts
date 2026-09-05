@_default: lint type-check test

@_uv:
    uv -V 2> /dev/null || { echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'; exit 1;}

lint: _uv
    uv run ruff check --fix --show-fixes src/ tests/
    uv run ruff format src/ tests/

type-check: _uv
    uv run mypy src/ tests/

test: _uv
    uv run pytest -vv --nf
