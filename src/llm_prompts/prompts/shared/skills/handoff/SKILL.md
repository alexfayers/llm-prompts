---
name: handoff
description: Write a handoff document so a fresh session (or another agent) can resume multi-session work with full context. Use when the current session is ending mid-effort, context is running high, or the user asks to "hand off", "hand over", or prepare the next session/slice.
---

# handoff

Produce a single self-contained handoff document that lets a brand-new session
resume the work with no prior context, then stop. A good handoff is the shortest
document from which someone could rebuild your mental model - not a diary.

## Where it goes

Write to `HANDOFF.md` in the workspace root (or the directory the work lives in),
unless the user names another location. One handoff doc at a time - if a stale
`HANDOFF.md` exists and is no longer relevant, overwrite it.

## Required structure

The document MUST open with a self-delete instruction as step 1, so the resuming
session removes the doc before doing anything else (it is scaffolding, not a
durable artifact - durable facts belong in memory and committed docs):

```markdown
# Handoff: <what is being handed off>

## Step 0 - Delete this doc first
Before doing anything else, delete this file (`HANDOFF.md`). It is a one-shot
handoff, not a durable record. The real record is in memory ([[entity-name]]) and
the committed code/docs.
```

Then include, in order:

1. **Where things stand.** What was just completed (with the commit/branch it
   landed on), and what state the tree/build/tests are in right now. Name the
   branch and whether it is pushed.
2. **The next task, stated concretely.** What "done" looks like for the next
   slice, and the very first action to take (e.g. "run test X - it is the
   ready-made RED").
3. **Key memory entities to load first.** An explicit list of the memory
   entities (and their project scope) the resuming session should read before
   starting - the `task/`, `feature/`, and `pattern/` entities that hold the
   durable detail, each with a one-line note of what it covers. This is the
   primary pointer into context; make it a real list, e.g.:
   - `task/<id>` (project `<name>`) - status + what's done/pending
   - `feature/<area>` - the subsystem being changed
   - `pattern/<name>` - reusable technique that applies
4. **Load-bearing context the code doesn't show.** Decisions already made and why,
   dead ends already ruled out (so they aren't re-explored), and any gotcha /
   fidelity gap that will bite the next session. Reference the memory entities
   from step 3 with `[[entity-name]]` rather than restating their detail.
5. **Known failures / caveats.** Anything red that is expected/pre-existing vs.
   anything the next session must fix - so a failing test isn't misread.
6. **Verification commands.** The exact build/test invocations to confirm the
   starting state and to check the next slice.

## Rules

- **Memory first, doc second.** Everything durable (decisions, outcomes, reusable
  learnings, task status) MUST already be in the memory graph before you write the
  handoff - the doc only points at it and frames the immediate next move. If it
  isn't in memory yet, persist it now (see the `session-end` skill).
- **Do not dump the diff or the play-by-play.** Link the commit; summarise intent.
- **Keep it scannable.** Bullet points and short sections. If the doc is longer
  than what someone will read before starting, it has failed.
- **Point to the plan.** If a plan file exists for the effort, reference it.
- After writing the doc, run the `session-end` checklist (commit/push status,
  outstanding TODOs) and tell the user the handoff is ready and where it lives.
