# Self-Improving - Cline-specific

**IMPORTANT: When surfacing queued tasks, use `ask_followup_question` to ask the user which one they'd like to continue on - do NOT call `attempt_completion` directly.**

**Only call `attempt_completion` AFTER the user responds, OR if there are no queued tasks.**

**Once the user selects a queued task, begin it immediately by calling `new_task` - do NOT call `attempt_completion` first.**
