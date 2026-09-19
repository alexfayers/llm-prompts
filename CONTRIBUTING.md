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

`main` is protected - direct pushes are rejected, so all changes go through a PR (squash or rebase merge only).

For a change under `src/llm_prompts/prompts/**` (rules, skills, workflows, agents), commit straight to your local `main` and use `contribute list`/`sync` instead of a manual branch - never push a feature branch for these:

- Commit the rule/skill change directly to your local `main`. This is what `llm-prompts update` installs from, so committing there lets you try the change live in your own agent session before it's even in a PR.
- `llm-prompts contribute list` shows every unmerged `prompts/**` commit's derived branch and whether it's new, needs syncing, or already `ok`.
- `llm-prompts contribute sync --apply` cherry-picks each pending commit onto a fresh disposable branch (never by moving a branch pointer, which would drag in every earlier unmerged commit too) and force-pushes it. Re-running `sync` after amending/rewording the commit on `main` re-derives and re-pushes the same branch.
- Never commit directly to a `contribute`-derived branch - the next `sync` run treats it as regenerable from `main` and overwrites it.
- A branch whose source commit was dropped from `main` becomes an orphan; `sync --apply` deletes orphans with no open PR automatically, or clean one up manually with `sync --cleanup <branch>`.

For everything else, push your own branch and open a PR against `main` as usual.

## PR titles and descriptions

- Title in conventional-commit format (`type: subject`).
- Description as bullet points, not paragraphs.
- State WHAT changed and WHY, not HOW.
- No restating the diff, no process commentary, no filler.
