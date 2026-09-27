---
name: eagle-vision
description: Break a problem into an implementation graph, layer by layer, until agents can build it unaided. Use to plan work for autonomous or parallel agents, or when the user says to use eagle vision.
---

# Eagle Vision

Output: an implementation graph - nodes with defined inputs, outputs, scope and acceptance criteria, built in parallel. Decide what each node must do; its builders decide how.

## 1. Research

- Where needed, SHOULD run read-only agents in parallel, one per independent area (docs, codebase, related repos).
- SHOULD verify with a quick experiment only plan-changing claims that are fast to check.

## 2. Direction

- Unless the user has an approach, SHOULD have 2+ design agents work from different angles, merged into proposed approaches with a recommendation; the user picks one before layer 1.

## 3. Plan in layers

The current layer is the first empty `PLAN.md` section.

1. Goal
2. Approach
3. Components
4. Interfaces - only what crosses a component boundary: entry functions and shared data shapes, with formats and usage; no internal helpers, field lists, per-case mechanics or code
5. Graph - nodes, dependencies and each node's scope (files, database objects, doc sections - any `/`-separated path); overlapping scope limits real parallelism
6. Nodes - acceptance criteria, one node at a time

- MUST agree a layer's content with the user before writing it to any plan file; MUST NOT start the next layer until the user says "next".
- MUST explain each item in plain words, not bare paths or names; show only the current layer or what changed - the full plan only when asked.
- MUST show Graph and Nodes from `focus.py` output, never retyped; MUST first check every scope path names a real file or symbol.
- Every decision MUST use AskUserQuestion with a recommended option, max 3 per call, rest held. Text just before the call is hidden - put the content in the question or option preview, or show it in an earlier turn.
- Each message MUST open with progress: layer or node, elapsed time (`date`), time left - baseline Goal 1m, Approach 13m, Components 1m, Interfaces 8m, Graph 13m, 5m per node, autonomy check 13m, scaled by pace so far.
- MUST be strict about scope creep: log a tangent under "Later" and return; raise it as a decision if it changes the plan.
- At each layer, question anything unused or unnecessary; keep it simple.

## 4. Graph shape

- Shared interfaces first; every other node depends only on them. Integration, an end-to-end check and docs last.
- Smallest single-job nodes - offer parallel work at every point.
- A node's acceptance tests and implementation SHOULD be separate tasks, built in parallel.
- Keep shared and case-specific logic in separate nodes.

## 5. Acceptance criteria

A node's only tests - write no others. Each criterion:

- MUST be a plain "if X, then Y" test of final behaviour and purpose, not mechanism; mark concrete names as examples "(e.g. ...)", dropping them once wording is precise.
- MUST check one thing - split compound ones.
- MUST stand alone: name its subject (no bare "it"/"this"), define vague verbs, no filler or relative time ("now", "as today") - state the outcome.
- MUST NOT repeat another node's criterion, or check log lines or other nodes; an end-to-end node checks user journeys through the real command.
- SHOULD be 5-6 per node, MUST NOT exceed 8.
- Review each node's criteria alone: one AskUserQuestion keep/change/drop question per criterion, 4 per call.

## 6. Plan directory

Manage it with `focus.py`, plan directory first (`python3 "<base-dir>/focus.py" <command> <dir> ...`):

- `init`, `add "<name>" [--depends ...] [--scope ...]`, `link`/`unlink <node> [--depends ...] [--scope ...]`, `remove <node>`, `rename <node> "<name>"`: change the plan.
- `built <node>`: awaiting tests. `pass <node>` / `fail <node> "<one-sentence reason>"`: done, or back to to-do with the reason kept. Only passing tests mark a node done.
- `show <node>`: everything an agent needs to build that node. `ready <node>`: whether its dependencies are done. `waves`: build order and progress.
- `PLAN.md` also holds Constraints (rules the build must follow, verified facts) and Later.
- Fill sections by editing files directly; never hand-edit the generated Graph, Scope and Nodes sections or node frontmatter - `focus.py` output confirms each change; don't re-read.
- Each node MUST be self-contained: only what a fresh session needs, no reasoning or history.

## 7. Autonomy check

- MUST run one fresh `worker-haiku-low` agent per node (not a `model` override), told it is read-only, using only `focus.py show <node>` plus Grep and offset-limited Read of code - never `PLAN.md`.
- Ask: "if every dependency were built to plan, could an agent build this node with no human?" Reply a bare YES; only a NO gives reasons.
- Not blockers: unbuilt dependency code or tests, files the node creates, exact signatures, call patterns and other details an implementer decides. Blockers: contradictions, missing interfaces, user-only decisions.
- Fix what they find; ask the user anything only they can decide; repeat until every agent answers YES.
