# Memory - Cline-specific guidance

## project vs global placement

- `.clinerules/` contents and workspace-specific rules discovered mid-session belong in `memory-project`, not `memory-global`.
- **NEVER put workspace-specific facts (repo names, file paths, `.clinerules` contents, tool configs specific to a repo) into `memory-global`.**
- When in doubt: if the fact only applies to the current workspace, it goes in `memory-project`.
