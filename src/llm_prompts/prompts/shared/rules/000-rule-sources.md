# Rule Sources

When editing rules, workflows, prompts, or skills, always edit the **source files** in the repository - never edit the installed copies.

Run `llm-prompts source {{AGENT}}` to see the source file paths for all installed rules, workflows, and skills.

After editing any source file, run `llm-prompts install {{AGENT}}` to reinstall.

For initial setup or full reinstall of all tools and overlays, use `llm-prompts setup`. Config is at `~/.config/llm-prompts/config.toml` - run `llm-prompts setup --init` to create it.

Commit rule, workflow, and skill changes as you go - do not accumulate them for a single commit at the end.
