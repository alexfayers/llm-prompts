# Self-Improving Reflection

**Objective:** Continuously improve {{RULE_FILES}} based on user interactions and feedback.

**Trigger:** Before you {{TOOL_COMPLETE}} for any task that involved user feedback at any point during the conversation, or involved multiple non-trivial steps.

**Immediate Corrections:** When the user corrects a mistake mid-conversation, do NOT wait until task completion. Immediately persist the correction to memory - this needs no permission. Where it is a repeatable behaviour affecting every user, follow the `llm-prompts-edit` skill to propose a {{RULE_FILES}}/skill edit.

**Self-Resolved Mistakes:** When you make a mistake and fix it yourself, persist the learning to memory immediately. If it reveals a missing process step that should be enforced for every user, follow `llm-prompts-edit` to propose one.

**Heuristic:** Changes how you work AND applies to every user -> a {{RULE_FILES}}/skill edit via `llm-prompts-edit`. User-specific details, or information about the world -> memory only.

**Process:**
1. **Always Reflect:** Before you {{TOOL_COMPLETE}}, synthesize all feedback from the conversation against the active {{RULE_FILES}}.
2. **Identify Active Rules:** List the specific {{RULE_FILES}} active during the task.
3. **Propose improvements, apply only what is permitted:** Write memory updates immediately. For any {{RULE_FILES}} or skill edit, follow `llm-prompts-edit`.
4. **Check for outstanding TODOs or side-requests** noted during the session. If any exist, mention them and suggest tackling them next.

**Constraint:** Do not offer reflection if no {{RULE_FILES}} were active, or the task was very simple with no feedback.
