---
name: eagle-vision
description: Break a problem into an implementation graph, layer by layer, until agents can build it unaided. Use to plan work for autonomous or parallel agents, or when the user says to use eagle vision.
---

# Eagle Vision

Output: a graph of nodes (inputs, outputs, scope, acceptance criteria) built in parallel. You decide what each does, builders how.

## Research

- SHOULD run read-only agents in parallel, one per area (docs, code, related repos, conventions).
- SHOULD quick-test only fast-to-check, plan-changing claims.
- Unless the user has an approach, SHOULD merge 2+ design agents' differing angles into options, one recommended.
- The user picks before layer 1.

## Plan in layers

The current layer is the first empty `PLAN.md` section.

1. Goal
2. Approach
3. Components
4. Interfaces - only what crosses a component boundary (entry functions, shared data shapes, helpers, test fixtures) with formats and usage, not internal helpers, field lists, per-case mechanics or code
5. Graph - nodes, dependencies, inputs, outputs and deletes (Interfaces items or existing symbols), scope (`/`-separated paths: files, DB objects, doc sections)
6. Nodes - acceptance criteria, one node at a time

- MUST write a layer to a plan file only once the user approves its text.
- MUST start the next only on "next".
- MUST explain items plainly, not bare paths or names.
- MUST show only the current layer or changes unless asked.
- MUST show Graph and Nodes from `focus.py` output, never retyped, after checking scope paths and existing inputs are real.
- Every decision MUST use {{TOOL_ASK_QUESTION}} with a recommended option, context in the question, max 3 per call, rest held.
- Each message MUST open with progress: layer or node, elapsed (`date`), time left from measured pace, or `?`.
- Scope creep: MUST log tangents under "Later".
- A plan-changing tangent is a decision.
- Each layer: question anything unneeded and keep it simple.

## Graph shape

- First: `join`'s interface nodes (contract plus mock), helpers and a `test-fixtures` node all tests reuse.
- End-to-end and docs last.
- Smallest single-job nodes, shared and case-specific logic apart, parallel everywhere.
- Scope MUST NOT list files no criterion covers.
- Each node MUST leave Checks green, updating callers of signatures it changes - red for later nodes is a plan defect.

## Acceptance criteria

A node's only tests - write no others. Each criterion:

- MUST be a plain "if X, then Y" test of final behaviour and purpose, not mechanism.
- Mark concrete names "(e.g. ...)" until wording is precise.
- MUST check one thing - split compound ones.
- MUST stand alone: name its subject (no bare "it"/"this"), define vague verbs, no filler or relative time ("now") - state the outcome.
- MUST NOT repeat another node's criterion, or check log lines or other nodes.
- SHOULD be 5-6 and MUST NOT exceed 8.
- SHOULD cover boundaries (empty, caps, paging).
- End-to-end nodes test user journeys with the real command and tools, sandboxed, no pushes or fakes.
- MUST NOT drop or weaken a real-tool test.
- Review each node alone, keep/change/drop per criterion, 4 per {{TOOL_ASK_QUESTION}}.
- Past ~20 nodes, MAY instead have one drafter then one checker per dir ({% if TOOL_WORKFLOW %}{{TOOL_WORKFLOW}}, else {% endif %}Agents), ask only their judgment calls, then one approval per dir.

## Plan directory

- Manage it with `python3 "<base-dir>/focus.py" <command> <dir> ...` - `-h` per command.
- Multi-repo: one plan dir per repo, as siblings, under a parent PLAN.md holding only the shared layers.
- Cross-repo order MUST be `--depends <dir>/<node>`.
- SHOULD run commands on the parent with `<dir>/<node>` ids.
- `set-test` with the criteria.
- After Graph, MUST run `join` until clean, and fix or accept each warning.
- Only `check` marks a node done.
- `PLAN.md` holds Constraints (build rules, verified facts, target branch, conventions e.g. commit rules), Checks (one `- <cmd>` per full gate command: tests, lint, format, types), Collect (one `- <cmd>` with `{test}`, failing on zero tests) and Later.
- Fill sections by editing, never generated ones (Graph, Scope, Nodes) or frontmatter.
- Trust `focus.py` output - don't re-read.
- Each node MUST be self-contained for a fresh session, no reasoning or history.

## Autonomy check

- MUST give each node a fresh `eagle-vision-checker-haiku-low` with only its brief file (`focus.py briefs <dir> --out <folder>`).
- {% if TOOL_WORKFLOW %}With {{TOOL_WORKFLOW}}, MUST run `autonomy-check.js` as {% if AGENT == "pi" %}`scriptPath`{% else %}`script`{% endif %}, paths as `args`, else {% endif %}one {{TOOL_AGENT}} call per node.
- MUST NOT dismiss a NO: fix it (asking the user what only they decide) or re-run the changed nodes, until none say NO.

## Build

- Per wave, MUST run `build-wave.js` {% if TOOL_WORKFLOW %}with {{TOOL_WORKFLOW}} as {% if AGENT == "pi" %}`scriptPath`{% else %}`script`{% endif %}, args{% else %}by hand, one {{TOOL_AGENT}} per `agent()` call, with{% endif %} `{plan: <dir>, skill: <base-dir>, wave, stamp}` (`probeOnly` before wave 1).
- Build steps go in `<dir>/build.sh`, overriding the script's `HOOKS`.
- MUST fix each escalation (asking the user what only they decide), then `resume: true`.
- MUST check running waves every 5 min and hand off to a new lead every 3-4 waves or before 300k context.
- Last, agents MUST run Constraints' post-build steps, `tidy-code` new source and tests, then review and fix the diff (max 2 rounds, rest to user).
