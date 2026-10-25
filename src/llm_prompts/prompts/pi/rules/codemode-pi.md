---
roles: all
---

# Codemode - pi-specific

- MUST put independent reads in one codemode script.
- MUST chain a dependent call in the same script where its input follows from the previous result.
- When a result is truncated, MUST find the tool's paging or filter docs, then fetch every page in one script.
- Where a schema hint shows a result shape, MUST read `r.structuredContent`, not `JSON.parse(r.content[0].text)`. Where it is absent, search the text by match.
- MUST NOT `.slice()` a result you have not seen, nor return a web/page/doc read (any tool fetching a page or URL) whole - filter by match.
- SHOULD put a memory write in the next codemode script you run.
- MUST print rejected results from `Promise.allSettled`.
- MUST NOT declare a codemode script variable named `tools`.
- Where the tool name is known, MUST NOT search for it. Before its first call, MUST read its arguments with `describeTool("mcp__<server>__<name>")` unless its schema is already in context.
- Where a named tool is not available, MUST report it missing and stop - MUST NOT look for a substitute.
- To wait for a changing result (CI, PR, job), SHOULD prefer an event-driven wait. Only where no event exists, MAY poll in one script with `await tools.sleep({ ms })` between checks.
