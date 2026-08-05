# Context Window Management

## Efficient Tools
- Prefer dedicated read/search/edit/write tools over shell commands for file operations - a dedicated tool returns only the relevant content, while a shell command dumps everything into context
- NEVER read or filter a whole file's contents via shell commands (e.g. `cat`, `grep`, `head`, `tail`) when a dedicated read/search tool is available - use that instead
- NEVER read an entire large file at once. Instead, search it with a targeted query/pattern, or read it in bounded chunks
- Prefer targeted, scoped queries over broad searches
