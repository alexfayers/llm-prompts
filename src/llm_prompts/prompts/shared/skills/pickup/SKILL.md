---
name: pickup
description: Resume work from an existing HANDOFF.md. Use when a HANDOFF.md is present in the workspace, the user says "do/resume/pick up the handoff", or points you at a handoff doc.
---

# pickup

An existing `HANDOFF.md` is present and the ask is to *execute* the work it
describes, not to write a new one. This skill is the resuming half of the
`handoff` skill - use `handoff` itself only when you are the one ending a
session and need to write the doc.

## Procedure

1. Read `HANDOFF.md`, plus any memory entities/plan file it points to. The doc
   sits at the session's workspace root, NOT inside the repo the work is about.
   Before concluding none exists, MUST check every workspace root:
   `find <roots> -maxdepth 3 -iname 'HANDOFF*.md'`.
2. Delete it as its own standalone tool call - do not chain the delete with
   another command (e.g. `rm HANDOFF.md && git status`). A chained command
   fails as a unit if the other half trips a permission/hook gate (such as a
   skill-usage requirement on `git`), which silently leaves the doc undeleted.
3. Go straight into the "next task, stated concretely" section as your first
   action.

Only fall back to the `handoff` skill's write flow if the user's wording is
actually about ending *this* session or handing off to someone else - if in
doubt, treat "do the handoff" for an already-existing doc as an instruction to
act on it, not to verify or rewrite it.

## Do not re-verify claims the handoff or memory already states as fact

You have zero prior context by design - the handoff doc and the memory
entities it points to ARE the full record, not a summary to be checked against
reality. Re-running `git status`/`git log`/an audit/a full re-fetch of
already-quoted entity content "just to confirm" is redundant work that adds
nothing (the writing session already did it) and, if repeated every time,
turns into a loop where sessions spend their budget re-deriving the same
starting state instead of advancing the task - the exact failure this skill
exists to prevent.

Trust stated facts (branch, commit, test status, prior session's findings) as
given. The only reason to re-check something is if the handoff itself flags it
as unverified/stale/"re-confirm before using" - that flag is the signal, not a
general policy of skepticism toward handoff content. If a claim turns out to
be wrong despite not being flagged, that's a defect in how the doc was
written, not a sign that every resume needs a verification pass - note it in
memory so the `handoff` skill can be reinforced, then keep moving.

This covers facts the writing session owned - branch, commits, test results,
findings. It does not cover state owned by a system outside the repo (ticket,
deployment, or review status): that changes on its own after the doc is
written, so read it from its own system when the current task turns on it, and
never present a handoff-recorded value as the current state.

## After finishing the handed-off work

Run `session-end` as normal when the work concludes. If more multi-session
work remains, use `handoff` to write a fresh doc for the next slice.
