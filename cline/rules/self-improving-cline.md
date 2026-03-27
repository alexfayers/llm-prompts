# Self-Improving Cline Reflection

**Objective:** Offer opportunities to continuously improve `.clinerules` based on user interactions and feedback.

**Trigger:** Before using the `attempt_completion` tool for any task that involved user feedback provided at any point during the conversation, or involved multiple non-trivial steps (e.g., multiple file edits, complex logic generation).

**Process:**

1.  **Always Reflect:** Before calling `attempt_completion`, always synthesize all feedback provided by the user throughout the entire conversation history for the task. Analyze how this feedback relates to the active `.clinerules` and identify areas where modified instructions could have improved the outcome or better aligned with user preferences.
2.  **Identify Active Rules:** List the specific global and workspace `.clinerules` files active during the task.
3.  **Apply Improvements Directly:** Generate specific, actionable improvements to ALL relevant files and apply them immediately - no need to ask for confirmation first. This includes `.clinerules/` rule files, skill `SKILL.md` files, and memory (both project and global). Prioritize suggestions directly addressing user feedback.
4.  **Then check for any outstanding TODOs or side-requests noted during the session** (in memory, TODO.md, or the {{TASK_PROGRESS}} list). If any exist, mention them to the user and suggest tackling them next - either inline or by starting a new task. Do not silently call `attempt_completion` without surfacing queued work.

**IMPORTANT: When surfacing queued tasks, use `ask_followup_question` to ask the user which one they'd like to continue on - do NOT call `attempt_completion` directly.**

**Only call `attempt_completion` AFTER the user responds, OR if there are no queued tasks.**

**Once the user selects a queued task, begin it immediately by calling `new_task` - do NOT call `attempt_completion` first.**

**Constraint:** Do not offer reflection if:
*   No `.clinerules` were active.
*   The task was very simple and involved no feedback.
