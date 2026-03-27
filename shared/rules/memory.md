---
description: Guide {{agent}} on using mcp-memory-sqlite for persistent memory.
---

# Memory Usage with mcp-memory-sqlite

You have one MCP memory server available: `memory`

All tools require a `project` parameter that scopes data. Use two logical projects:

- `global` - for cross-project knowledge (user preferences, patterns, reusable techniques)
- `<repo-name>` - for project-specific knowledge (e.g. `fayers-mcp-memory-sqlite`)

You can (and should) use these MCP tools in _both_ PLAN and ACT mode.

You _do not_ need to let the user know if/when you are interacting with memory.

Ensure you _always_ update memory as you progress through a task, and just before you complete it.

## When to use which project scope

- Use `project="global"` for:
  - General user preferences (coding style, stack choices, tooling).
  - Cross-project summaries - brief notes about recent work across projects.
  - Reusable patterns and techniques (infra patterns, testing approach, migration strategies).
  - Long-lived knowledge that should be shared across projects.
  - For project-related entries, keep observations short and summary-level.
  - Update after any change (successful or failed - note failures explicitly), any new information gained from the user, and any insight discovered during the task.

- Use `project="<repo-name>"` for:
  - Architecture, design decisions, and constraints specific to this repo.
  - Module/API contracts, invariants, and non-obvious gotchas.
  - Project-specific user preferences that don't apply globally.
  - TODOs, partial work, and context that only matters in this codebase.

- **NEVER put workspace-specific facts (repo names, file paths, workspace specific rules, tool configs specific to a repo) into global memory.**
- When in doubt: if the fact only applies to the current workspace, it goes in project memory.

### If the `memory` server is unavailable

If `memory` is not accessible and you need it for the current task:
1. Start the server: `SQLITE_DB_PATH=~/.memory/memory.db alexfayers-mcp-memory-sqlite`
2. Ask the user to reload the MCP connection.
3. Do not continue until `memory` is available.

## Before starting a task

For ANY and EVERY task, you **MUST** follow ALL of these steps - no exceptions, no shortcuts!

**CRITICAL: Do NOT respond to the user until ALL steps below are complete.** Skipping steps 3-5 defeats the purpose of having memory. `read_graph` alone is not enough - it only returns recent entities and misses deeper context.

1. **ALWAYS** use `read_graph(project="global")` first - this surfaces recent global entities. Never skip this step.
2. **ALWAYS** use `read_graph(project="<repo-name>")` second - this surfaces recent project entities.
3. **ALWAYS** use `search_nodes(project="global")` to find entities related to the user's request. Search for:
    - Keywords and terms from the user's message (e.g. file names, feature names, ticket IDs)
    - `user-preferences` (always search this - it contains workflow and coding style rules)
    - The current project/repository name
    - Any relevant `pattern/` entities (e.g. `pattern/aws-lambda-debugging`, `pattern/dynamodb-batch-get-retry`) - search for keywords related to the tools/services being used
4. **ALWAYS** use `search_nodes(project="<repo-name>")` to find entities related to:
    - Keywords and terms from the user's message
    - The current file(s) or directory being worked on
    - Any feature or ticket identifiers mentioned in the request
    - `STATUS in-progress` (always search this - it finds any unfinished task entities for the current project)
5. **ALWAYS** use `get_entity_with_relations` on every relevant entity found in steps 3-4. This traverses the graph to discover linked context that search alone would miss.
    - **ALWAYS** call `search_related_nodes(project="<repo-name>", name="project/<current-project>", entityType="task")` to find all task entities for the current project.

6. If relevant entities exist:
    - Briefly summarize what is already known before making a plan.
    - Highlight prior decisions, constraints, and pitfalls.

## Entity and observation standards

Use consistent naming and entity types to maximize discoverability:

### Entity naming

Entity names must be unique across all entity types. Always prefix the name with the entity type to prevent collisions:

| What | Entity type | Name format | Example |
|---|---|---|---|
| A repository / codebase | `project` | `project/<repo-name>` | `project/ExampleProject` |
| A feature area or module | `feature` | `feature/<project>/<area>` | `feature/ExampleProject/ticketing` |
| A task or ticket | `task` | `task/<TICKET-ID>-<slug>` | `task/ABC-123-idempotency-simplification` |
| A user preference or style | `user-preferences` | `user-preferences/<alias>-<topic>` | `user-preferences/fayers-workflow` |
| A reusable pattern | `pattern` | `pattern/<short-noun>` | `pattern/dynamodb-batch-get-retry` |
| A completed change | `changelog` | `changelog/<TICKET-ID>-<slug>` or `changelog/<project>-<date>-<slug>` | `changelog/ABC-123-idempotency-simplification` |

### Task entity discipline

**CRITICAL: In-progress work MUST be tracked as a separate `task/` entity - never as observations on a `project/` entity.**

- Every `task/` entity MUST include a `STATUS:` observation: `STATUS: in-progress`, `STATUS: blocked`, or `STATUS: complete`
- Task entities MUST be linked to their parent project with a `belongs-to` relation
- When starting a new piece of work, create the `task/` entity and relation immediately - before writing any code
- When completing a task, update its STATUS observation from `in-progress` to `complete`
- Do not store implementation details or work-in-progress notes on the `project/` entity

### Entity relations

Memory is a graph database - use `get_entity_with_relations` to traverse linked entities and discover connected context.

**CRITICAL: You MUST call `create_relations` whenever you call `create_entities`.** Relations are the core of the graph model - entities without relations are nearly useless. Always link new entities to existing ones.

Every entity MUST have at least one relation, except `user-preferences` and `pattern` entities which are global singletons not tied to a specific project.

Use relations to link related entities, e.g.:
- task `implements` feature
- task `belongs-to` project
- feature `belongs-to` project
- pattern `used-in` project
- changelog `modified` project or feature
- changelog `follows` previous changelog (chain chronological changes for full history traversal)

### Observation wording

Use entity type to distinguish current facts from past actions:

- **`project` / `feature` observations** - use present tense for current facts: "process_ticket requires relationship_manager"
- **`changelog` / `task` observations** - use past tense for completed actions: "Removed is_tracked and is_processed_or_tracked helpers"
- Do not include rationale in the same observation as the fact - add a separate observation for "why"

## While working

- **CRITICAL: Hook reminders appear as `<hook_context>` blocks in the environment details. When you see one, you MUST act on it in your NEXT tool call - before doing anything else. Do NOT defer, skip, or queue it for later.**
- As you discover important facts (architecture decisions, API contracts, subtle bugs, performance findings, etc.), update memory with observations worth persisting.
- Prefer small, precise observations over long narrative text.
- Each observation must be **atomic** - one fact per observation. Never combine multiple distinct facts into a single observation string (e.g. do not write "X was done (Y is also true)" - instead add two separate observations).
- Group related observations under a single entity for the project or feature when possible.
- **IMPORTANT: `create_entities` OVERWRITES all existing observations for an entity.** To append new observations without risk of data loss, use `add_observations` instead. Only use `create_entities` when you need to replace all observations or create a new entity. If you must use `create_entities` on an existing entity, always call `get_entity_with_relations` first to read existing observations and include ALL of them.
- Use `add_observations` to safely append new facts to an existing entity - it deduplicates automatically and throws if the entity doesn't exist.
- Use `delete_observations` to remove specific observations by exact content match - it returns the count deleted and throws if the entity doesn't exist.

## After completing a task or reaching a milestone

For each significant unit of work (feature implemented, bug fixed, refactor completed), and **BEFORE** calling the `attempt_completion` tool:

1. Using `project="<repo-name>"`:
    - Ensure there is an entity representing this project and, if useful, one for the specific feature/area.
    - Add new observations describing:
      - What changed
      - Why it changed (rationale)
      - Any important consequences, caveats, or follow-up TODOs.
    - Update the `task/` entity STATUS observation from `in-progress` to `complete`.

2. When the knowledge is reusable across projects:
    - Also update `project="global"` with a concise, generalized observation.
    - Avoid project-specific details in global memory; focus on patterns and lessons.

3. If a memory is no longer relevant, was incorrect, or would actively mislead future sessions, use `delete_entity` and/or `delete_relation` to remove it. Use this sparingly - prefer marking things deprecated in text unless the memory would cause harm.

## Answering memory-related questions

When the user asks questions like:

- "What do you already know about this project / file / feature?"
- "What have we decided about X so far?"
- "What did we learn from previous work on this?"

You should:

1. Query `project="<repo-name>"` for the most relevant entities and their observations.
2. Optionally query `project="global"` if broader patterns or preferences might be relevant.
3. Present a concise summary, grouped by entity/topic.
4. Clearly distinguish between project-specific memory and global, cross-project knowledge.

## Memory rules

- When creating an implementation plan, always include memory updates in the plan
- Always share these rules with any subagents
- Query memory before starting a task
- Update memory as you go - don't just wait until the end of a task
- **ALL knowledge not stored in memory or prompt files is permanently lost at the end of each session.** This includes things told to you mid-session (e.g. user preferences, model config, tool behaviour). Always persist this kind of information immediately to `project="global"`.
- Calling `new_task` starts a fresh context window - treat it the same as ending a session. **Persist all important knowledge to memory before calling `new_task`.**
