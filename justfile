ts_test_heap_mb := "4096"
ts_test_timeout_seconds := "900"

@_default: lint _checks

[parallel]
_checks: type-check type-check-ts (test "1") test-ts check

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

test alongside="0": _uv
    TEST_RUNS_ALONGSIDE={{alongside}} uv run pytest -q --nf -n auto --dist worksteal --cov=. --cov-report=xml

test-ts: _pnpm
    NODE_OPTIONS=--max-old-space-size={{ts_test_heap_mb}} node tests/ts/run-with-timeout.mjs {{ts_test_timeout_seconds}} node --test --experimental-test-module-mocks tests/ts/*.test.ts

check: _uv
    uv run llm-prompts check

# Seed state for the upgrade smoke test. Setup of the latest release already seeds all of it.
upgrade-seed:
    @echo 'upgrade-seed: the latest release setup holds all the state upgrade-smoke checks.'

# Check an upgraded install: the tool env's startup imports, an update under the hook resource caps, and Claude Code files that match this checkout.
upgrade-smoke: _uv
    #!/usr/bin/env bash
    fail() { echo "upgrade-smoke: $*" >&2; exit 1; }
    tool_python="$(uv tool dir)/llm-prompts/bin/python"
    [ -x "$tool_python" ] || fail "no llm-prompts tool env at $tool_python."
    startup_check="$(uv run python -c 'from llm_prompts.setup import _STARTUP_CHECK; print(_STARTUP_CHECK)')" \
        || fail "this checkout cannot report its startup check."
    "$tool_python" -c "$startup_check" || fail "the installed tool env cannot run '$startup_check'."
    # Runs a command under the data, CPU and git pack caps the installed cline-hooks gives its hooks and their children.
    hook_capped() {
        "$tool_python" -c '
    import os, resource, sys
    from cline_hooks._main import _limit_resources
    _limit_resources()
    data = resource.getrlimit(resource.RLIMIT_DATA)[0]
    cap = "no data limit" if data == resource.RLIM_INFINITY else f"a {data >> 20} MB data limit"
    print(f"upgrade-smoke: running {sys.argv[1:]} under {cap}.", file=sys.stderr)
    os.execvp(sys.argv[1], sys.argv[1:])
    ' "$@"
    }
    hook_capped gh --version > /dev/null || fail "gh failed under the cline-hooks resource caps (CLINE_HOOKS_MAX_MEMORY_MB)."
    hook_capped llm-prompts update < /dev/null \
        || fail "llm-prompts update failed under the cline-hooks resource caps (CLINE_HOOKS_MAX_MEMORY_MB)."
    rendered="$(cd "$(mktemp -d)" && pwd -P)"
    trap 'rm -r "$rendered"' EXIT
    # The render reads the MCP servers, and so the memory tool names agents list, from .claude.json.
    if [ -f "$HOME/.claude.json" ]; then cp "$HOME/.claude.json" "$rendered/"; fi
    # Renders with this checkout's code and the overlay packages the upgrade installed.
    PYTHONPATH='{{justfile_directory()}}/src' "$tool_python" -c 'from llm_prompts.cli import main; raise SystemExit(main())' \
        install claude-code --no-update --root "$rendered" > /dev/null \
        || fail "this checkout cannot render the claude-code files."
    # Skills embed their own install path.
    find "$rendered/.claude" -type f -exec env FROM="$rendered" perl -pi -e 's/\Q$ENV{FROM}\E/$ENV{HOME}/g' {} +
    for dir in rules agents; do
        diff -r "$rendered/.claude/$dir" "$HOME/.claude/$dir" \
            || fail "~/.claude/$dir does not match what this checkout builds."
    done
    for skill in "$rendered"/.claude/skills/*; do
        diff -r "$skill" "$HOME/.claude/skills/${skill##*/}" \
            || fail "~/.claude/skills/${skill##*/} does not match what this checkout builds."
    done
    echo 'upgrade-smoke: the upgraded install matches this checkout.'
