---
name: eagle-vision
description: Break a problem into an implementation graph, layer by layer, until agents can build it unaided. Use to plan work for autonomous or parallel agents, or when the user says to use eagle vision.
---

# Eagle Vision

Output: an implementation graph of nodes (inputs, outputs, scope, acceptance criteria) built in parallel; decide what each does, builders how.

## Research

- SHOULD run read-only agents in parallel, one per area (docs, code, related repos, project or domain conventions).
- SHOULD quick-test only fast-to-check, plan-changing claims.
- Unless the user has an approach, SHOULD merge 2+ design agents' differing angles into options, one recommended; the user picks before layer 1.

## Plan in layers

The current layer is the first empty `PLAN.md` section.

1. Goal
2. Approach
3. Components
4. Interfaces - only what crosses a component boundary (entry functions, shared data shapes, helpers, test fixtures) with formats and usage; no internal helpers, field lists, per-case mechanics, code
5. Graph - nodes, dependencies, inputs, outputs and deletes (Interfaces items or existing symbols), scope (`/`-separated paths: files, DB objects, doc sections)
6. Nodes - acceptance criteria, one node at a time

- MUST write a layer to a plan file only once the user approves its text; start the next only on "next".
- MUST explain items plainly, not bare paths or names; show only the current layer or changes unless asked.
- MUST show Graph and Nodes from `focus.py` output, never retyped, after checking scope paths and existing inputs are real.
- Every decision MUST use AskUserQuestion with a recommended option, max 3 per call, rest held. Text just before the call is hidden - use the question, preview or an earlier turn.
- Each message MUST open with progress: layer or node, elapsed (`date`), time left from measured pace, or `?`.
- Scope creep: MUST log tangents under "Later"; plan-changing ones are decisions.
- Each layer: question anything unneeded; keep it simple.

## Graph shape

- First: `join`'s interface nodes (contract plus mock), helpers and a `test-fixtures` node all tests reuse. End-to-end and docs last.
- Smallest single-job nodes, shared and case-specific logic apart, parallel everywhere.
- Scope MUST NOT list files no criterion covers.

## Acceptance criteria

A node's only tests - write no others. Each criterion:

- MUST be a plain "if X, then Y" test of final behaviour and purpose, not mechanism; mark concrete names "(e.g. ...)", dropped once wording is precise.
- MUST check one thing - split compound ones.
- MUST stand alone: name its subject (no bare "it"/"this"), define vague verbs, no filler or relative time ("now") - state the outcome.
- MUST NOT repeat another node's criterion, or check log lines or other nodes.
- SHOULD be 5-6, MUST NOT exceed 8; cover boundaries (empty, caps, paging).
- End-to-end nodes test user journeys with the real command and tools, sandboxed, no pushes or fakes; MUST NOT drop or weaken a real-tool test.
- Review each node alone: one AskUserQuestion keep/change/drop per criterion, 4 per call.

## Plan directory

- Manage it with `python3 "<base-dir>/focus.py" <command> <dir> ...`: `init`, `add`/`link`/`unlink` (`--depends|--scope|--inputs|--outputs|--deletes`), `remove`, `rename`, `join`, `set-test`, `built`, `check`, `pass`/`fail`, `show`, `ready`, `waves`; `-h` explains each.
- `set-test` with the criteria; after Graph, MUST run `join` until clean; only `check` marks a node done.
- `PLAN.md` holds Constraints (build rules, verified facts, target branch, project or domain conventions like commit rules), Checks (one `- <cmd>` per full gate command: tests, lint, format, types) and Later.
- Fill sections by editing, never generated ones (Graph, Scope, Nodes) or frontmatter; trust `focus.py` output, don't re-read.
- Each node MUST be self-contained for a fresh session, no reasoning or history.

## Autonomy check

- MUST give each node a fresh `eagle-vision-checker-haiku-low` with only its `focus.py briefs <dir>` entry inline: `plan`, then the node. With Workflow, MUST run `autonomy-check.js` as `script` with that JSON as `args`; else one Agent call per node.
- MUST NOT dismiss a NO: fix it (asking the user what only they can decide) or re-run the changed nodes, until none say NO.

## Build

- MUST spawn one standing `eagle-vision-sentinel-sonnet-medium`: target from Constraints, integration branch `ev/<plan>`, gate `focus.py check <dir> <node> --base ev/<plan>`; tell it each `ready` node.
- MUST spawn a fresh test writer and implementer per node worktree from `show <node>`, docs too, no `coordinator`. Neither messages the other, runs tests or sleeps; gaps go to the lead. The implementer runs `built <node>`, then messages the sentinel.
- Once all are done, MUST `tidy-code` the new source and tests, then review and fix its diff (max 2 rounds; rest to user); the sentinel then lands `ev/<plan>` on the target.
