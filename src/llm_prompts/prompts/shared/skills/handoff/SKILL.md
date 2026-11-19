---
name: handoff
description: Write a handoff doc for a fresh session to resume work. Use when ending mid-effort, context high, or user says hand off. Resuming uses `pickup`.
---

# handoff

If the invocation names a part (a sibling `<part>.md`, e.g. `live`), MUST read `<base-dir>/<part>.md` first.

Write one self-contained, minimal handoff doc a new session can resume from with no prior context.
Then stop the work it hands over, unless the doc compacts the context or goes to an explicitly parallel session.

## Where it goes

A live handoff continues the work in a fresh session.

{% if AGENT == "pi" %}
Unless starting a new session, MUST pass the doc as the `compact_now` `instructions` and omit Step 0.
MUST use `change_dir` for a cwd or worktree change only when the tool is available and permits the move.
MUST NOT write `HANDOFF.md` or start a new session unless the user asks, the work needs a parallel session, the env or process must change, or the cwd or worktree cannot change in this session.
When starting a new session, {% if has_command("herdr") %}MUST follow the next paragraph.{% else %}write `HANDOFF.md`.{% endif %}

{% endif %}
{% if has_command("herdr") %}
Inside Herdr (`test "${HERDR_ENV:-}" = 1`),{% if AGENT == "pi" %} when starting a new session,{% endif %} MUST send the doc live per `<base-dir>/live.md` and omit Step 0,
unless the user asks for a disk handoff or has opted out.{% if AGENT != "pi" %} Otherwise:{% endif %}

{% endif %}
{% if AGENT == "pi" %}Only for a disk handoff{% if has_command("herdr") %} or outside Herdr{% endif %}, write{% else %}Write{% endif %} to `HANDOFF.md` in the workspace root
(or the directory the work lives in),
unless the user names another location. One handoff doc at a time - overwrite a
stale `HANDOFF.md`.

- Before writing, MUST read any existing `HANDOFF.md` and confirm it belongs to
  the current effort.
- Where it belongs to a different effort, MUST NOT overwrite it - append a new
  section or write a differently-named file instead, and surface the collision
  to the user.

## Two directions: writing vs. resuming

This skill *writes* a handoff. "do/resume/pick up the handoff" means *execute*
an existing `HANDOFF.md` - use `pickup`. If in doubt, treat "do the handoff"
for an existing doc as `pickup`, not a rewrite.

## Required structure

The document MUST open with a self-delete instruction as step 1:

```markdown
# Handoff: <what is being handed off>

## Step 0 - Delete this doc first
Before doing anything else, delete this file (`HANDOFF.md`). The real record
is in memory ([[entity-name]]) and the committed code/docs.
```

Then include, in order:

1. **Where things stand.** What was just completed (commit/branch), and the
   tree/build/test state. Name the branch and whether it is pushed.
2. **The next task, stated concretely.** What "done" looks like for the next
   slice, and the first action to take.
3. **Key memory entities to load first.** An explicit list of `task/`,
   `feature/`, and `pattern/` entities (with project scope) to read first, each
   with a one-line note, e.g.:
   - `task/<id>` (project `<name>`) - status + what's pending
   - `feature/<project>/<capability>` - its gotchas and decisions
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
{% if AGENT == "pi" %}
- Before writing, MUST `fork_steer` each live background fork to reach a commit or
  checkpoint and report its state, and MUST read the result message it sends before ending.
- The doc and the reply MUST name every `fork` worktree not yet landed and what state it left.
{% else %}
- Before writing, MUST `SendMessage` each running delegate to reach a commit or
  checkpoint and report its state, and MUST wait for that report before
  `TaskStop`. A handoff request is not an instruction to stop in-flight work.
  The doc and the reply MUST name every delegate stopped and what state it left.
{% endif %}
- **Memory first, doc second.** Durable facts (decisions, learnings,
  task status) MUST already be in the memory graph before you write the
  handoff. If not yet persisted, do so now (see
  the `session-end` skill).
- No diff dump or play-by-play. Link the commit; summarise intent. Use bullets.
- Point to the plan file, if any.
- MUST point the resuming session at the governing rules file for the
  workspace (if any) and at the authoritative memory entity for the effort -
  not just at the doc itself.
- For multi-step work, MUST instruct the resuming session to track steps with
  the harness task tools ({% if AGENT == "pi" %}`tower_do`/`tower_do_status`{% else %}TaskCreate/TaskUpdate/TaskList{% endif %}), updating status as
  it goes.
- For multi-phase work, MUST carry context (or explicit references: file:line,
  gate) for EVERY remaining phase, not only the next one.
- After writing the doc, run the `session-end` skill, except its step 4 task
  review. If you came here from `session-end`, do not run it again. Then tell
  the user where the doc lives.
