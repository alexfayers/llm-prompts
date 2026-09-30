# Asking the user

- Every question to the user - a decision, clarification, confirmation or missing value - MUST go through the `AskUserQuestion` tool, never plain response text. This is how every "ask the user" in other rules is delivered.
- Where `AskUserQuestion` is deferred, MUST load it via `ToolSearch` with `select:AskUserQuestion` first.
- MUST list the recommended option first. MUST put context the answer depends on in the question or option descriptions - text just before the call is hidden.
- Re-asking a pending ask per `anti-yap.md` MUST use the tool again.
- Statements, status notes and rhetorical phrasing are not questions; MUST NOT end a message with a question outside the tool.
- A subagent or teammate MUST NOT ask the user - it escalates to its lead per `agent-teams.md` and `stop-on-fail.md`; the session talking to the user asks.
- Plan approval goes through `ExitPlanMode` and tool permissions through the harness prompt, not `AskUserQuestion`; a follow-up question after a denial still uses it.
- Where `AskUserQuestion` is unavailable or errors (headless or background session), MUST ask in plain text and stop.
