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
- `llm-prompts contribute list` shows every unmerged `prompts/**` commit's batch branch and status (new, current, stale, regressed, or already in another open PR), across every locally-cloned overlay repo in your config by default - pass `--tool NAME` to narrow it to one.
- Pending commits are grouped into batches of up to 5 and appended, in order, to the newest open `<login>/contribute/<slug>` branch with room; once that batch is full or merged, a new one starts.
- `llm-prompts contribute sync --apply` pushes each batch: one whose commits are all still current gets the new ones cherry-picked on top and pushed normally; one with an amended or missing commit is rebuilt from `main` and pushed with `--force-with-lease`.
- `llm-prompts contribute sync --commit SHA` (repeatable) syncs only the batches holding those commits: it appends to the newest open batch with room, otherwise starts a new one, and leaves everything else local.
- Repos merge by squash only and require PRs up to date with `main`; `llm-prompts contribute list` warns about any of your open PRs (batch or hand-made) that are behind, and `llm-prompts contribute update --apply` rebases each onto `main` with `gh pr update-branch --rebase` (dry run without `--apply`; `--tool NAME --pr N` for one PR). Rebasing keeps batch commit matching intact; never update with a merge commit.
- `contribute` uses `gh` when installed; otherwise it calls the GitHub API with `GH_TOKEN`, `GITHUB_TOKEN`, or your git credential helper's github.com token. Without gh and without push access, fork first: rename `origin` to `upstream` and add your fork as `origin`.
- A commit already in one of your other open PRs is skipped and shown in `list` as already in that PR.
- Never commit directly to a batch branch - `sync` treats it as regenerable from `main` and may overwrite it.
- A regressed batch (holding a commit matching nothing on `main`) gets a recovery hint that cherry-picks just the missing commits back on top.
- An open PR on a non-batch branch that holds a commit local `main` lacks (same subject and author time) shows it as `[not on main]` under that PR, with a hint to cherry-pick it onto `main`; `list` then exits 1.

For everything else, push your own branch and open a PR against `main` as usual.

## PR titles and descriptions

- Title in conventional-commit format (`type: subject`).
- Description as bullet points, not paragraphs.
- State WHAT changed and WHY, not HOW.
- No restating the diff, no process commentary, no filler.
