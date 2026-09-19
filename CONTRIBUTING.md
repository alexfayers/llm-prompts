# Contributing

## Setup

`llm-prompts` needs a sibling checkout of [cline-hooks](https://github.com/alexfayers/cline-hooks) - `pyproject.toml`'s `[tool.uv.sources]` pins it as an editable relative path (`../cline-hooks`), and `src/llm_prompts/hooks.py` imports it unconditionally, so tests fail to collect without it:

```bash
git clone https://github.com/alexfayers/llm-prompts.git
git clone https://github.com/alexfayers/cline-hooks.git
cd llm-prompts
uv sync
```

## Checks

```bash
just    # lint, type-check, test (see justfile for the individual commands)
```

Runs `ruff check --fix`, `ruff format`, `mypy` (strict), and `pytest` via `uv run`. Run all of these before opening a PR - there's no CI workflow yet, so this is the only gate.

## Prompt file size budgets

Files under `src/llm_prompts/prompts/**` (rules, skills, workflows, agents) are subject to enforced size budgets, checked by `tests/test_prompt_sizes.py` and separately live: editing a tracked rule/skill/workflow/agent source file triggers cline-hooks' auto-reinstall, which blocks the write outright if the result would push that file over its threshold. If you hit this, compress the file's wording rather than splitting it into multiple files or asking to raise the ceiling - the fix preserves every existing directive in fewer bytes.

## Commit messages

Single-line, conventional-commit style (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:` ...), no body. Match `git log --oneline -20` for tone.

## Pull requests

`main` is protected - direct pushes are rejected, so all changes go through a PR (squash or rebase merge only). Push your branch and open a PR against `main`.

## PR titles and descriptions

- Title in conventional-commit format (`type: subject`).
- Description as bullet points, not paragraphs.
- State WHAT changed and WHY, not HOW.
- No restating the diff, no process commentary, no filler.
