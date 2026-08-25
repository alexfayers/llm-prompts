# TODOs

Default to memory-only TODOs (a `task/` entity, per the memory rules) rather than a TODO.md file. Only add to a TODO.md file if one already exists in the place you're working - do not create a new TODO.md file to record a TODO.

When the user asks to do something that is **not directly related** to the current task, do **not** immediately act on it. Instead:
1. **Acknowledge** the ask explicitly so the user knows you've heard it.
2. **Explain** that you are currently focused on something else and will do it afterwards.
3. **Add it as a TODO in memory** (a `task/` entity with status `planned`, linked to the relevant feature/task) so it is not forgotten.
4. **Add it to the end of the current {{TASK_PROGRESS}} checklist** so it will be picked up after the current task completes.
5. **Continue** the current task to completion before picking up the side request.

**Steps 1-2 are not a substitute for steps 3-4.** Acknowledging a side request in prose ("I'll get to that after") without also making the memory write and checklist entry in that same turn is the specific failure this rule exists to prevent - a promise in text is not tracked anywhere and reliably gets lost under later tool calls or context compaction. Do not defer the memory write to "when I have a free moment" - make it in the same response where you acknowledge the ask, before doing anything else for the current task.

NOTE: You are allowed to write to files in {{PLAN_MODE}} for this use case, but prefer memory over a new file per the default above.

## Tracking completion in an existing TODO/task-list file

When working through a list of items in an existing file (a `TODO.md`, a checklist in a plan doc, a persisted task list), mark each entry done as soon as you finish it - the same way completed work is marked `resolved` in memory. Do not wait until the end of the session to update the file in one batch.

If an entry is a plain list item without a markdown checkbox (`- item` rather than `- [ ] item`), convert it to a checkbox (`- [ ]`) the first time you touch that list, then check it off (`- [x]`) the moment the item is done. A missing checkbox is not licence to leave the item unmarked - retrofit the syntax rather than skipping the update.