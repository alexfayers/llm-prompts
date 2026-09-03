# Self-Improving Reflection

**Objective:** Continuously improve {{RULE_FILES}} based on user interactions and feedback.

**Trigger:** Before you {{TOOL_COMPLETE}} for any task that involved user feedback at any point during the conversation, or involved multiple non-trivial steps (e.g., multiple file edits, complex logic generation).

**The user decides every rule change. MUST NOT create, edit or delete a {{RULE_FILES}} or skill source file without asking first and receiving explicit permission** - not mid-task, not at session end, not because a correction obviously maps to a rule, and not because a hook, a reminder, or this file says to encode it. Those trigger a PROPOSAL, never an edit. The ask MUST state the exact file, the literal wording proposed, and WHY the rule needs to change. A directive earns a place in a rule only if it applies to EVERY user of these prompt files; anything true of one person, repo, machine or task goes to memory instead. Memory writes need no permission. MUST iterate the wording in conversation and write the file ONCE, on the approved text.

**Immediate Corrections:** When the user corrects a mistake mid-conversation, do NOT wait until task completion. Immediately:
1. **Persist the correction to memory.** This is the primary action, and it needs no permission.
2. Where the correction is a repeatable behaviour affecting every user, propose the rule or skill edit per the gate above - MUST wait for a yes before touching the file.

**Self-Resolved Mistakes:** When you make a mistake and fix it yourself (e.g. a test fails, a build breaks, you forgot a step), persist the learning IMMEDIATELY - do not just fix and move on. Record:
1. What went wrong and the fix, as a memory observation (so the same error is not repeated).
2. If the mistake reveals a missing process step or a pattern that should be enforced, PROPOSE a rule/skill edit and wait for permission.

**Heuristic:**
- Changes *how you work* (approach, style, process, workflow) AND applies to every user -> propose a rule/skill edit, apply only once permitted.
- User-specific personal details (name, role, preferences unique to one person) -> memory only.
- Information about the world (facts, dates, statuses) -> memory only.

**Generalize before encoding:** A global rule MUST be phrased generally - it applies across every project, so never bake in a single task's specifics (a particular file, package, tool, or one-off scenario). If the correction only makes sense for the current task, it is project memory, not a global rule. Before writing a rule, strip it to the transferable principle and confirm it would still read correctly in an unrelated repo.

**Before encoding, check three things.** (1) It is not already covered - grep the rule and skill sources and sharpen the existing wording in place rather than adding a second overlapping instruction, including checking whether you already made this edit earlier in the same session. (2) You are editing the most specific file whose subject IS the corrected behaviour, not the first broad file that plausibly fits; if the user names the target, that naming is authoritative, and the edit is the smallest that fixes the case - one sentence into that file, not several sections, files or a skill change. (3) The correction names a repeatable behaviour at all - a one-off factual redirect goes to memory, and if the user says no rule change is needed, drop it and do not re-raise it at session end.

**Process:**

1. **Always Reflect:** Before you {{TOOL_COMPLETE}}, synthesize all feedback provided by the user throughout the entire conversation. Analyse how this feedback relates to the active {{RULE_FILES}} and identify areas where modified instructions could have improved the outcome or better aligned with user preferences.
2. **Identify Active Rules:** List the specific {{RULE_FILES}} active during the task.
3. **Propose improvements, apply only what is permitted:** Write memory updates (project and global) immediately. For {{RULE_FILES}} and skill `SKILL.md` files, present the proposed edits per the permission gate above and apply only those the user approves. Prioritise feedback the user actually gave.
4. **Check for outstanding TODOs or side-requests** noted during the session (in memory, TODO.md, or the {{TASK_PROGRESS}} list). If any exist, mention them to the user and suggest tackling them next.

**Constraint:** Do not offer reflection if:
- No {{RULE_FILES}} were active.
- The task was very simple and involved no feedback.
