# Self-Improving Reflection

**Objective:** Continuously improve {{RULE_FILES}} based on user interactions and feedback.

**Trigger:** Before you {{TOOL_COMPLETE}} for any task that involved user feedback at any point during the conversation, or involved multiple non-trivial steps (e.g., multiple file edits, complex logic generation).

**Immediate Corrections:** When the user corrects a mistake mid-conversation, do NOT wait until task completion. Immediately:
1. **Edit the relevant rule or skill source file.** This is the primary action - behavioral corrections MUST be encoded in rules/skills because they are always loaded into context. Memory must be actively searched for.
2. Also persist to memory for broader discoverability.

**Self-Resolved Mistakes:** When you make a mistake and fix it yourself (e.g. a test fails, a build breaks, you forgot a step), persist the learning IMMEDIATELY - do not just fix and move on. Record:
1. What went wrong and the fix, as a memory observation (so the same error is not repeated).
2. If the mistake reveals a missing process step or a pattern that should be enforced, edit the relevant rule/skill source file.

**Heuristic:**
- Changes *how you work* (approach, style, process, workflow) -> edit a rule/skill source file.
- User-specific personal details (name, role, preferences unique to one person) -> memory only.
- Information about the world (facts, dates, statuses) -> memory only.

**Process:**

1. **Always Reflect:** Before you {{TOOL_COMPLETE}}, synthesize all feedback provided by the user throughout the entire conversation. Analyse how this feedback relates to the active {{RULE_FILES}} and identify areas where modified instructions could have improved the outcome or better aligned with user preferences.
2. **Identify Active Rules:** List the specific {{RULE_FILES}} active during the task.
3. **Apply Improvements Directly:** Generate specific, actionable improvements to ALL relevant files and apply them immediately - no need to ask for confirmation first. This includes {{RULE_FILES}}, skill `SKILL.md` files, and memory (both project and global). Prioritise suggestions directly addressing user feedback.
4. **Check for outstanding TODOs or side-requests** noted during the session (in memory, TODO.md, or the {{TASK_PROGRESS}} list). If any exist, mention them to the user and suggest tackling them next.

**Constraint:** Do not offer reflection if:
- No {{RULE_FILES}} were active.
- The task was very simple and involved no feedback.
