# Response ordering - Kiro CLI rendering

In the Kiro CLI, any assistant text emitted *before* a tool call in a turn is rendered as dark grey "thinking" text. Only the text after the final tool call is displayed as the white reply the user actually reads.

Therefore:

- ALL substantive user-facing content (findings, analysis, answers, summaries) MUST come *after* the last tool call of the turn.
- Never front-load the full answer and then finish with a tool call (e.g. a memory write) followed by a one-line confirmation - the user will only see the confirmation.
- If a tool call is needed after the main content (memory persistence, counters, etc.), make the tool call first and present the content afterwards, or repeat the content in full after the call.
