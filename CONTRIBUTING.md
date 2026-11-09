# Contributing

## Setup

`uv sync` installs [cline-hooks](https://github.com/alexfayers/cline-hooks) from GitHub, as `pyproject.toml`'s `[tool.uv.sources]` declares:

```bash
git clone https://github.com/alexfayers/llm-prompts.git
cd llm-prompts
uv sync
```

## Checks

```bash
just    # lint, type-check, test (see justfile for the individual commands)
```

Runs `ruff check --fix`, `ruff format`, `mypy` (strict), and `pytest` via `uv run`. Run all of these before opening a PR - CI runs lint, type-check, and test on every push and PR.

## Prompt file size budgets

Files under `src/llm_prompts/prompts/**` (rules, skills, workflows, agents) are subject to enforced size budgets, checked by `tests/test_prompt_sizes.py` and separately live: editing a tracked rule/skill/workflow/agent source file triggers cline-hooks' auto-reinstall, which blocks the write outright if the result would push that file over its threshold. If you hit this, compress the file's wording rather than splitting it into multiple files or asking to raise the ceiling - the fix preserves every existing directive in fewer bytes.

## Commit messages

Single-line, conventional-commit style (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:` ...), no body. Match `git log --oneline -20` for tone.

## Pull requests

`main` is protected - direct pushes are rejected, so all changes go through a PR (squash or rebase merge only).

For a change under `src/llm_prompts/prompts/**` (rules, skills, workflows, agents), work in a `git worktree` on your own branch and use `contribute` instead of pushing the branch yourself. Each worktree branch is one PR, squash-merged:

```sh
git worktree add ../my-change -b my-change origin/main
llm-prompts contribute sync --tool NAME --branch my-change   # record it, local only
llm-prompts contribute sync --apply                          # copy it into local main
llm-prompts contribute sync --tool NAME --ready my-change    # let sync push it and open a draft PR
llm-prompts contribute sync --apply
```

- `sync --apply` never pushes or opens a PR for a local-only worktree. Once `--ready`, it pushes the branch, opens a draft PR and keeps its title and What current.
- Stack a branch on another with `--depends-on B TOOL:B2`. `sync` restacks it and writes the `Depends on` line.
- Run `llm-prompts contribute sync --help` for every flag, and `contribute list` for each worktree's state and size.
- Marking a contribute PR ready for review enables squash auto-merge. It merges once checks pass and a reviewer approves.
- When main moves, open PRs with auto-merge on are rebased onto it automatically.
- Never commit to local `main` for a recorded worktree. `sync` replaces its copy.
- Repos merge by squash only and require PRs up to date with `main`. `llm-prompts contribute update --apply` rebases your open PRs behind `main`.
- `contribute` uses `gh` when installed. Otherwise it calls the GitHub API with `GH_TOKEN`, `GITHUB_TOKEN`, or your git credential helper's github.com token. Without gh and without push access, fork first: rename `origin` to `upstream` and add your fork as `origin`.

For everything else, push your own branch and open a PR against `main` as usual.

Add fixes for review feedback to the PR as new commits - do not amend or rebase them away - so reviewers can see what changed.

## PR titles and descriptions

- Title in conventional-commit format (`type: subject`).
- Description as bullet points, not paragraphs.
- State WHAT changed and WHY, not HOW.
- No restating the diff, no process commentary, no filler.
- List a PR that must merge first as a `Depends on <PR URL>` line (`contribute sync` writes it for a linked worktree); the `check-dependencies` check fails until it merges and re-checks when that PR closes. A PR or issue closing in a private repo never rechecks PRs in a public repo.

## Copilot review

- The four files `review.instructions.md`, `prompts.instructions.md`, `python.instructions.md` and `typescript.instructions.md` under `.github/instructions` here are the single place to edit the Copilot review rules.
- The `Sync review rules` workflow opens bot PRs in cline-hooks and mcp-memory with a copy of them.
- When Copilot submits a review, its earlier reviews on that PR are marked outdated.
- Copilot approvals do not count toward `min-reviews` labels.
