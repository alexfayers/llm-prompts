# Self-Improving Reflection

**Objective:** Continuously improve {{RULE_FILES}} based on user interactions and feedback.

**Trigger:** Before you {{TOOL_COMPLETE}} for any task that involved user feedback at any point during the conversation, or involved multiple non-trivial steps (e.g., multiple file edits, complex logic generation).

**Immediate Corrections:** When the user corrects a mistake mid-conversation, do NOT wait until task completion. Immediately:
1. Persist the learning to memory (project and/or global scope as appropriate).
2. Check whether the correction should also be added to a {{RULE_FILES}} or skill - if so, update it now.

**Process:**

1. **Always Reflect:** Before you {{TOOL_COMPLETE}}, synthesize all feedback provided by the user throughout the entire conversation. Analyse how this feedback relates to the active {{RULE_FILES}} and identify areas where modified instructions could have improved the outcome or better aligned with user preferences.
2. **Identify Active Rules:** List the specific {{RULE_FILES}} active during the task.
3. **Apply Improvements Directly:** Generate specific, actionable improvements to ALL relevant files and apply them immediately - no need to ask for confirmation first. This includes {{RULE_FILES}}, skill `SKILL.md` files, and memory (both project and global). Prioritise suggestions directly addressing user feedback.
4. **Check for outstanding TODOs or side-requests** noted during the session (in memory, TODO.md, or the {{TASK_PROGRESS}} list). If any exist, mention them to the user and suggest tackling them next.

**Constraint:** Do not offer reflection if:
- No {{RULE_FILES}} were active.
- The task was very simple and involved no feedback.
