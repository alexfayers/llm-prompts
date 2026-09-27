---
name: eagle-vision
description: Break a problem into an implementation graph, layer by layer, until agents can build it unaided. Use to plan work for autonomous or parallel agents, or when the user says to use eagle vision.
---

# Eagle Vision

Output: an implementation graph - nodes with inputs, outputs, scope and acceptance criteria, built in parallel. Decide what each node does; builders decide how.

## 1. Research

- SHOULD run read-only agents in parallel, one per area (docs, code, related repos).
- SHOULD quick-test only fast-to-check, plan-changing claims.

## 2. Direction

- Unless the user has an approach, SHOULD have 2+ design agents take different angles, merged into options, one recommended; the user picks before layer 1.

## 3. Plan in layers

The current layer is the first empty `PLAN.md` section.

1. Goal
2. Approach
3. Components
4. Interfaces - only what crosses a component boundary: entry functions, shared data shapes, helpers and test fixtures, with formats and usage; no internal helpers, field lists, per-case mechanics, code
5. Graph - nodes, dependencies and each node's scope (any `/`-separated path: files, DB objects, doc sections); overlapping scope limits parallelism
6. Nodes - acceptance criteria, one node at a time

- MUST agree a layer with the user before writing it to a plan file; start the next only on the user's "next".
- MUST explain items plainly, not bare paths or names; show only the current layer or changes, full plan on request.
- MUST show Graph and Nodes from `focus.py` output, never retyped, after checking each scope path is a real file or symbol.
- Every decision MUST use AskUserQuestion with a recommended option, max 3 per call, rest held. Text just before the call is hidden: use the question, option preview or an earlier turn.
- Each message MUST open with progress: layer or node, elapsed (`date`), time left - baseline Goal 1m, Approach 13m, Components 1m, Interfaces 8m, Graph 13m, 5m per node, autonomy check 13m, scaled by pace.
- Scope creep: MUST log a tangent under "Later" and return; raise it as a decision if plan-changing.
- Each layer: question anything unneeded; keep it simple.

## 4. Graph shape

- First: shared interfaces, helpers and a `test-fixtures` node all tests reuse; other nodes depend only on them. Integration, end-to-end check and docs last.
- Smallest single-job nodes, shared and case-specific logic apart - offer parallel work everywhere.

## 5. Acceptance criteria

A node's only tests - write no others. Each criterion:

- MUST be a plain "if X, then Y" test of final behaviour and purpose, not mechanism; mark concrete names "(e.g. ...)", dropped once wording is precise.
- MUST check one thing - split compound ones.
- MUST stand alone: name its subject (no bare "it"/"this"), define vague verbs, no filler or relative time ("now") - state the outcome.
- MUST NOT repeat another node's criterion, or check log lines or other nodes; end-to-end nodes check user journeys via the real command.
- SHOULD be 5-6, MUST NOT exceed 8.
- Review each node alone: one AskUserQuestion keep/change/drop per criterion, 4 per call.

## 6. Plan directory

Manage it with `python3 "<base-dir>/focus.py" <command> <dir> ...`:

- `init`, `add "<name>"`, `link`/`unlink <node>` (last three: `[--depends ...] [--scope ...]`), `remove <node>`, `rename <node> "<name>"`: change the plan.
- `set-test <node> "<cmd>"`: its test command, set with its criteria. `built <node>`: awaiting tests. `check <node>`: runs that, then Checks - pass or fail. `pass`/`fail <node> "<one-sentence reason>"`: done, or back to to-do, reason kept. Only passing tests mark a node done.
- `show <node>`: all a builder needs. `ready <node>`: dependencies done? `waves`: build order and progress.
- `PLAN.md` holds Constraints (build rules, verified facts), Checks (full gate commands - tests, lint, format, types - one `- <cmd>` each) and Later.
- Edit files to fill sections, never generated ones (Graph, Scope, Nodes) or frontmatter - `focus.py` output confirms each change; don't re-read.
- Each node MUST be self-contained for a fresh session, no reasoning or history.

## 7. Autonomy check

- MUST run one fresh `surveyor-haiku-low` agent per node (not a `model` override), using only `focus.py show <node>`, Grep and offset-limited Read of code - never `PLAN.md`.
- Ask: "if every dependency were built to plan, could an agent build this node unaided?" Reply bare YES, or NO with reasons.
- Not blockers: unbuilt dependencies or tests, files the node creates, implementer details (signatures, call patterns). Blockers: contradictions, missing interfaces, user-only decisions.
- Fix findings, asking the user what only they can decide; repeat until all say YES.

## 8. Build

- Only once `ready <node>` passes, MUST spawn a fresh parallel pair from `show <node>`: one writes acceptance tests, one implements - no `coordinator`.
- One standing `worker-haiku-low` verifier per build ONLY runs `check <node>` from repo root, messaged by the implementer after `built <node>` once both finish.
- After all nodes are done, MUST run `tidy-code` on the build's new source and tests, then review its diff and fix the findings.
