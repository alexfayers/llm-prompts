---
name: eagle-vision
description: Break a problem into an implementation graph, layer by layer, until agents can build it unaided. Use to plan work for autonomous or parallel agents, or when the user says to use eagle vision.
---

# Eagle Vision

Output: an implementation graph - nodes with defined inputs, outputs, scope and acceptance criteria, designed to be built in parallel. This skill decides what each node must do, not how - implementation is deferred to the agents building it.

## 1. Research

- Where the problem needs it, SHOULD run read-only agents in parallel, one per independent area (docs, codebase, related repos).
- SHOULD verify, with a quick experiment, only claims that would change the plan if wrong and are fast to check.

## 2. Direction

- Skip where the user already has an approach.
- Otherwise SHOULD have 2+ design agents each work from a different angle, then merge them into proposed approaches with a recommendation.
- The user chooses one of the proposed approaches before layer 1 starts.

## 3. Plan in layers

One layer at a time, each agreed with the user and written to its `PLAN.md` section before going deeper. MUST NOT go deeper than the current layer until asked. The current layer is the first empty section.

1. Goal
2. Approach
3. Components
4. Interfaces - data shapes, signatures, formats and usage; no code
5. Graph - nodes, dependencies, what builds in parallel
6. Scope - what each node owns
7. Nodes - acceptance criteria per node

- Every decision put to the user MUST come with at least one suggested answer.
- MUST NOT ask more than 3 decisions at a time; hold the rest until the user answers that batch.
- MUST NOT dump the whole plan on the user - show only the current layer or what changed. Show the full plan only when asked.
- MUST be strict about scope creep: when the user raises a tangent, acknowledge it, record it under "Later", and return to the current layer. If it would change the current plan, raise it as a decision instead.
- At each layer, question anything unused or unnecessary; keep it simple.

## 4. Graph shape

- Shared interfaces first; every other node depends only on them. Integration, an end-to-end check and docs come last.
- Break everything into the smallest single-job nodes - offer parallel work at every point.
- A node's acceptance tests and its implementation are separate tasks, built in parallel.
- Keep shared logic and case-specific logic in separate nodes.

## 5. Acceptance criteria

- The final behaviour a node must have: what it accepts as input and what it must output.
- Bullets, each one concrete and checkable.
- They are the node's only tests.

## 6. Plan directory

Manage it with `focus.py` - every command takes the plan directory first (`python3 "<base-dir>/focus.py" <command> <dir> ...`):

- `init`, `add "<name>" [--depends ...] [--scope ...]`, `link`/`unlink <node> [--depends ...] [--scope ...]`, `done <node>`: change the plan.
- `show <node>`: everything an agent needs to build that node.
- `ready <node>`: whether a node's dependencies are done.
- `waves`: build order and progress - done, ready and waiting nodes.

- `PLAN.md` also holds Constraints (rules the build must follow, verified facts) and Later.
- Fill section contents by editing the files directly; never hand-edit the Graph, Scope or Nodes sections or a node's frontmatter - `focus.py` generates them.
- The script's output confirms each change; don't re-read files to check.
- Each node MUST be self-contained.
- Only what a fresh session needs - no reasoning or history.

## 7. Autonomy check

- MUST have fresh read-only agents answer: "could agents finish this with no human?" - flagging only real contradictions or user-only decisions, not details an implementer can decide.
- SHOULD use lightweight agents - if they can follow it, the plan is clear.
- Best: one agent per node, via `focus.py show`. Acceptable: one agent for the whole plan per pass.
- Fix what they find; ask the user anything only they can decide; repeat until every agent answers YES.
