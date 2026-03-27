# Memory - Cline-specific guidance

## project vs global placement

- `.clinerules/` contents and workspace-specific rules discovered mid-session belong in project memory, not global memory.

## Memory rules

- Calling `new_task` starts a fresh context window - treat it the same as ending a session. **Persist all important knowledge to memory before calling `new_task`.**
