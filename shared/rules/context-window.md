# Context Window Management

## Efficient Tools
- ALWAYS prefer MCP tools (`search_files`, `replace_in_file`, `write_to_file`) over `execute_command` for file operations
- NEVER USE shell commands (`cat`, `head`, `tail`, etc.) to read file contents - use `read_file` or `search_files` instead
- NEVER USE the `read_file` tool for large files. Instead, ALWAYS search with `search_files` using specific patterns
- Use targeted queries vs broad searches
- Avoid running CLI commands when MCP tools are available instead
- If a file has potential to be large, NEVER read the entire file at once
- ALWAYS use MCP tools instead of large file reads and CLI commands

## New Tasks
Monitor usage: `# Context Window Usage: X / YK tokens used (Z%)`

**> Z >= 70% OR X >= 200k -> Create new task using `new_task`**
**> Large operation will be performed in next steps -> Create new task using `new_task`**
**>New step doesn't require previous context -> Create new task using `new_task`**
