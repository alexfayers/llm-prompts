# Context Window Management

## Efficient Tools
- SHOULD use dedicated read/search/edit/write tools over shell commands for file operations - a dedicated tool returns only the relevant content
- MUST NOT read or filter a whole file's contents via shell commands (e.g. `cat`, `grep`, `head`, `tail`) when a dedicated read/search tool is available
- MUST NOT read an entire large file at once. MUST search it with a targeted query/pattern, or read it in bounded chunks
- SHOULD use targeted, scoped queries over broad searches (compact memory searches excepted)
{% if AGENT == "pi" %}

## Checkpoint rewind
- SHOULD `checkpoint rewind` after a finished detour (investigation, debug loop, exploratory calls) once only its conclusion matters, and after large raw outputs (logs, diffs, dumps) already acted on
- Before compacting, MUST try a rewind first. Compact only when a rewind can't free enough (most of the context is old history)
- MUST NOT rewind over raw detail that later steps still need
- The rewind summary MUST keep every finding, decision and open ask from the folded region
{% endif %}
