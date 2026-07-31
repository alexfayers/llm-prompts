# TODOs

Default to memory-only TODOs (a `task/` entity, per the memory rules) rather than a TODO.md file. Only add to a TODO.md file if one already exists in the place you're working - do not create a new TODO.md file to record a TODO.

When the user asks to do something that is **not directly related** to the current task, do **not** immediately act on it. Instead:
1. **Acknowledge** the ask explicitly so the user knows you've heard it.
2. **Explain** that you are currently focused on something else and will do it afterwards.
3. **Add it as a TODO in memory** (a `task/` entity with status `planned`, linked to the relevant feature/task) so it is not forgotten.
4. **Add it to the end of the current {{TASK_PROGRESS}} checklist** so it will be picked up after the current task completes.
5. **Continue** the current task to completion before picking up the side request.

Each session should ideally cover one coherent change so commits stay manageable.

NOTE: You are allowed to write to files in {{PLAN_MODE}} for this use case, but prefer memory over a new file per the default above.