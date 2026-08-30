---
name: handoff
description: Write a handoff doc for a fresh session to resume work. Use when ending mid-effort, context high, or user says hand off/over/prepare next session. Resuming an existing HANDOFF.md uses `pickup`.
---

# handoff

Produce a single self-contained handoff document that lets a brand-new session
resume the work with no prior context, then stop. Write the shortest document
that lets someone rebuild your mental model - not a diary.

## Where it goes

Write to `HANDOFF.md` in the workspace root (or the directory the work lives in),
unless the user names another location. One handoff doc at a time - overwrite a
stale `HANDOFF.md` that is no longer relevant.

## Two directions: writing vs. resuming

This skill covers *writing* a handoff at session end. "do/resume/pick up the
handoff" means an existing `HANDOFF.md` should be *executed*, not rewritten -
use the `pickup` skill instead. If in doubt, treat "do the handoff" for an
existing doc as a `pickup` instruction, not a rewrite.

## Required structure

The document MUST open with a self-delete instruction as step 1 (it is
scaffolding, not a durable artifact - durable facts belong in memory and
committed docs):

```markdown
# Handoff: <what is being handed off>

## Step 0 - Delete this doc first
Before doing anything else, delete this file (`HANDOFF.md`). It is a one-shot
handoff, not a durable record. The real record is in memory ([[entity-name]]) and
the committed code/docs.
```

Then include, in order:

1. **Where things stand.** What was just completed (commit/branch), and the
   tree/build/test state. Name the branch and whether it is pushed.
2. **The next task, stated concretely.** What "done" looks like for the next
   slice, and the first action to take.
3. **Key memory entities to load first.** An explicit list of `task/`,
   `feature/`, and `pattern/` entities (with project scope) to read first, each
   with a one-line note, e.g.:
   - `task/<id>` (project `<name>`) - status + what's done/pending
   - `feature/<area>` - the subsystem being changed
   - `pattern/<name>` - reusable technique that applies
4. **Load-bearing context the code doesn't show.** Decisions made and why,
   dead ends ruled out, and gotchas/fidelity gaps. Reference step-3 entities
   with `[[entity-name]]` rather than restating their detail.
5. **Known failures / caveats.** Expected/pre-existing red vs. what the next
   session must fix.
6. **Verification commands.** Exact build/test invocations for the starting
   state and for the next slice.

## Rules

- Write for a resuming session with zero prior context that will act on your
  claims without re-checking. State something as fact (a commit SHA, "tests
  pass") only if verified this session; mark anything inferred or relayed as
  "UNVERIFIED - re-check before relying on this".
- Do not push to get uncommitted work committed before writing the handoff,
  unless the user asks. Capture the tree as-is, dirty or not, and note what is
  uncommitted and where it lives.
- **Memory first, doc second.** Durable facts (decisions, outcomes, learnings,
  task status) MUST already be in the memory graph before you write the
  handoff - the doc only points at it. If not yet persisted, do so now (see
  the `session-end` skill).
- Do not dump the diff or the play-by-play. Link the commit; summarise intent.
- Keep it scannable: bullets, short sections.
- Point to the plan file if one exists for the effort.
- After writing the doc, run the `session-end` skill for the rest of session
  close (memory persisted, commit/push status resolved, rule-file reflection)
  - except its step 5 comprehensive TODO/task review, which this skill's own
  "next task" section already narrows to the current effort. Arrived here from
  `session-end` itself - do not re-invoke it. Then tell the user the handoff is
  ready and where it lives.
