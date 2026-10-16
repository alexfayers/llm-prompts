---
roles: lead, coordinator, reasoner
targets: claude-code, pi
---

# Asking the user

- Every question to the user - a decision, clarification, confirmation or missing value - MUST go through the `{{TOOL_ASK_QUESTION}}` tool, never plain response text. This is how every "ask the user" in other rules is delivered.
{% if AGENT == "pi" %}
- `{{TOOL_ASK_QUESTION}}` takes exactly one of `question` or `questions` (2-4 independent questions per batch); options are `{title, description}`, with `allowMultiple` and `allowFreeform` per question.
{% else %}
- Where `AskUserQuestion` is deferred, MUST load it via `ToolSearch` with `select:AskUserQuestion` first.
{% endif %}
- MUST list the recommended option first. MUST put context the answer depends on in the question or option descriptions. MUST NOT rely on reply text above the question - the dialog hides it. Where the context is the decision (a plan, a diff), MUST {% if AGENT == "pi" %}pass it with `contextExpanded: true`{% else %}put it in the question itself{% endif %}.
- Re-asking a pending ask per `anti-yap.md` MUST use the tool again.
- Statements, status notes and rhetorical phrasing are not questions; MUST NOT end a message with a question outside the tool.
- A subagent or teammate MUST NOT ask the user - it escalates to its lead per `agent-teams.md` and `stop-on-fail.md`; the session talking to the user asks.
{% if AGENT == "pi" %}
- Tool permissions go through the harness prompt, not `{{TOOL_ASK_QUESTION}}`; a follow-up question after a denial still uses it.
{% else %}
- Plan approval goes through `ExitPlanMode` and tool permissions through the harness prompt, not `AskUserQuestion`; a follow-up question after a denial still uses it.
{% endif %}
- Where `{{TOOL_ASK_QUESTION}}` is unavailable or errors (headless or background session), MUST ask in plain text and stop.
