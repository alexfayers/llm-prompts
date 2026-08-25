---
paths: '**/prompts/**/*, **/.claude/rules/*.md, **/.claude/skills/**/*, **/llm-prompts/config.toml'
kiro_inclusion: manual
---

# Rule Sources

When editing rules, workflows, prompts, or skills, always edit the **source files** in the repository - never edit the installed copies.

Rules and skills must be as terse as possible - short bullets only. Explain only where the rule would otherwise be ambiguous; prose that justifies or restates a rule is deleted, not shortened.

Run `llm-prompts source {{AGENT}}` to see the source file paths for all installed rules, workflows, and skills.

After editing any source file, run `llm-prompts update` to reinstall.

For initial setup or full reinstall of all tools and overlays, use `llm-prompts setup`. Config is at `~/.config/llm-prompts/config.toml` - run `llm-prompts setup --init` to create it.

## Rules request, hooks enforce

Rules and skills request compliance; only a cline-hooks handler actually enforces it by blocking or forcing an action.
Anything that genuinely must not happen belongs in a hook, not in a rule phrased with MUST/NEVER.
A MUST/NEVER for behaviour no hook checks asserts a guarantee the rule cannot actually deliver.
When writing or reviewing a rule, ask whether the behaviour is observable at a tool call or lifecycle event - if so, it should be a hook.

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
