# Rule Sources

When editing rules, workflows, prompts, or skills, always edit the **source files** in the repository - never edit the installed copies.

Run `llm-prompts source {{AGENT}}` to see the source file paths for all installed rules, workflows, and skills.

After editing any source file, run `llm-prompts install` to reinstall.

If the edited file is in an overlay package (e.g. mcp-memory/prompts/), run the full reinstall first:

```
uv tool upgrade llm-prompts --reinstall
```

Then run `llm-prompts install` to symlink the updated files.

Commit rule, workflow, and skill changes as you go - do not accumulate them for a single commit at the end.
