---
name: llm-prompts-edit
description: Author or edit llm-prompts' own rule, skill, workflow, or agent source files under src/llm_prompts/prompts/. Use before proposing or writing any change there.
---

# llm-prompts Source Editing

Decision order for touching this repo's own rule/skill/workflow/agent sources.

## 1. Gate

- MUST NOT create, edit or delete a rule or skill source file without an explicit yes in the current conversation - a correction, a hook reminder, or an obvious mapping is NOT permission.
- The proposal MUST name the exact file, the literal wording, and why. MUST iterate wording in conversation, write ONCE on the approved text.
- Persisting the learning to memory instead needs no permission.

## 2. Scope

- Generic across every project and person -> rule/skill. Specific to one person/repo/task -> memory, not here.
- A hook enforces with certainty; a rule/skill only requests compliance - prefer a hook when the behaviour is checkable at a tool call or lifecycle event.

## 3. Rule vs skill

- A rule always applies, everywhere. A skill is one process for one task. Not clear which -> escalate to the user for a decision.
- New mandatory skill also needs a trigger line in `002-skill-usage` - propose both together.

## 4. Dedup

- Find the real source file first with `llm-prompts source <agent>` (e.g. `claude-code`) - never guess a path.
- MUST grep the rule AND skill sources for existing coverage - sharpen the most specific match in place, not a second overlapping instruction.
- MUST check you did not already make this edit earlier in the session.
- Smallest edit that fixes the case - one sentence, not a new file.

## 5. Write

- RFC 2119 bullets only; no filler or justification.
- A skill is a directory: SKILL.md plus optional scripts. Prefer a script or hook over prose wherever the step is checkable or computable exactly.
- New skill: `src/llm_prompts/prompts/shared/skills/<name>/SKILL.md`, `name` = directory, `description` states what + when. Directory scan registers it.

## 6. Size

- Just write it. A hook blocks an oversized rule/skill/workflow file.
- Blocked -> compress that file: cut filler words, redundant reasoning, duplication, and restatements. Never split the file or raise the ceiling. In a multi-edit sequence, apply shrinking edits first.

## 7. Commit and PR

- Commit the change right after making it. Do not leave it uncommitted.
- If an unpushed commit already changes the same rule or skill, fix that commit up instead of making a new one.
- Keep a compression edit in its own commit, separate from the content change - easier to review.
- To open the change as a PR: @pr.md
