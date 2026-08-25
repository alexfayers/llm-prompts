---
kiro_inclusion: manual
---

# Rule Sources

When editing rules, workflows, prompts, or skills, always edit the **source files** in the repository - never edit the installed copies.

Run `llm-prompts source {{AGENT}}` to see the source file paths for all installed rules, workflows, and skills.

After editing any source file, run `llm-prompts update` to reinstall.

For initial setup or full reinstall of all tools and overlays, use `llm-prompts setup`. Config is at `~/.config/llm-prompts/config.toml` - run `llm-prompts setup --init` to create it.

**Commit rule, workflow, and skill changes as you go - this is a mechanical trip-wire, not a judgment call.** The moment you finish editing a source file under this rule (a rule, workflow, skill, or agent-config source), your very next git action on that repo MUST be staging and committing that file - before moving on to unrelated work, before a bare status/diff check for its own sake, and before ending the session. Do not accumulate multiple edits for a single commit at the end, and do not let "I'll commit later" survive past the current turn.

Before creating that commit, check whether HEAD is an unpushed commit covering the same rule/skill/topic (per `git-usage`'s amend-alignment rule) - if so, amend it instead of adding a new commit for what is really the same change landing in two steps.

**Pushing to the source repos.** If the local checkout's `origin` points at a fork (e.g. `codebeetl/llm-prompts`, forked from `alexfayers/llm-prompts`) because the authenticated account lacks push/merge rights on the upstream repo, push commits straight to the fork's `main` - it is the principal remote for this environment. Also open a PR from the fork to the corresponding upstream repo so the fix can flow back, and leave that PR open rather than trying to merge it (the account can't merge upstream); it's fine for the fork to run ahead of upstream in the meantime.

## Adding an overlay

To add an llm-prompts overlay package, add a `[[tools]]` entry to `~/.config/llm-prompts/config.toml`:

```toml
[[tools]]
name = "<package-name>"
source = "<git-url-or-local-path>"
overlays_for = ["llm-prompts"]
```

The `source` field must be a pip-installable reference:
- Git HTTPS: `git+https://github.com/user/repo.git`
- Git SSH: `git+ssh://host/path/to/repo`
- Local path: `~/path/to/repo`

If given a web URL to a repository, convert it to a `git+https://` or `git+ssh://` URL that pip can install from.

For local and git sources, `overlays_for`/`standalone` are inferred from the package's `pyproject.toml`, so they are optional overrides; bare PyPI sources still need them set explicitly.

Then run `llm-prompts setup` to install it, followed by `llm-prompts install {{AGENT}}` to apply the new rules, workflows, and skills.

## Adding memory

To add persistent memory via [mcp-memory](https://github.com/alexfayers/mcp-memory), add it to `~/.config/llm-prompts/config.toml`:

```toml
[[tools]]
name = "mcp-memory"
source = "git+https://github.com/alexfayers/mcp-memory.git"
standalone = true
overlays_for = ["llm-prompts"]
```

For local and git sources, `overlays_for`/`standalone` are inferred from the package's `pyproject.toml`, so they are optional overrides; bare PyPI sources still need them set explicitly.

Then run `llm-prompts setup` followed by `llm-prompts install {{AGENT}}`.

## Adding hooks

To add lifecycle hooks via [cline-hooks](https://github.com/alexfayers/cline-hooks), add it to `~/.config/llm-prompts/config.toml`:

```toml
[[tools]]
name = "cline-hooks"
source = "git+https://github.com/alexfayers/cline-hooks.git"
```

Then run `llm-prompts setup` followed by `llm-prompts install {{AGENT}}`.
