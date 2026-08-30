# Context Window Management

## Efficient Tools
- SHOULD use dedicated read/search/edit/write tools over shell commands for file operations - a dedicated tool returns only the relevant content
- MUST NOT read or filter a whole file's contents via shell commands (e.g. `cat`, `grep`, `head`, `tail`) when a dedicated read/search tool is available
- MUST NOT read an entire large file at once. MUST search it with a targeted query/pattern, or read it in bounded chunks
- SHOULD use targeted, scoped queries over broad searches
