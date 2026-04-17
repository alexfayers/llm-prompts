# Rule Sources

When editing rules, workflows, prompts, or skills, always edit the **source files** in the repository - never edit the installed copies.

Run `llm-prompts source {{AGENT}}` to see the source file paths for all installed rules, workflows, and skills.

After editing any source file, run `llm-prompts install {{AGENT}}` to reinstall.

For initial setup or full reinstall of all tools and overlays, use `llm-prompts setup`. Config is at `~/.config/llm-prompts/config.toml` - run `llm-prompts setup --init` to create it.

Commit rule, workflow, and skill changes as you go - do not accumulate them for a single commit at the end.

## Adding an overlay

To add an llm-prompts overlay package, add a `[[tools]]` entry to `~/.config/llm-prompts/config.toml`:

```toml
[[tools]]
name = "<package-name>"
source = "<git-url-or-local-path>"
overlays_for = ["llm-prompts"]
```

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

Then run `llm-prompts setup` followed by `llm-prompts install {{AGENT}}`.

## Adding hooks

To add lifecycle hooks via [cline-hooks](https://github.com/alexfayers/cline-hooks), add it to `~/.config/llm-prompts/config.toml`:

```toml
[[tools]]
name = "cline-hooks"
source = "git+https://github.com/alexfayers/cline-hooks.git"
```

Then run `llm-prompts setup` followed by `llm-prompts install {{AGENT}}`.
