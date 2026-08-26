---
name: retrospective
description: Analyse recent session transcripts to extract learnings, discover pain points, and persist them into memory/skills/rules. Run manually when the retrospective counter is due (session-end reminds you at 5+).
---

# retrospective

Analyse recent Claude Code sessions to surface patterns, corrections, and pain points that should become rules, memory, or skills.

## 1. Extract signals

Analyse exactly the sessions that have elapsed since the last retrospective. The `cline-hook` session counter tracks this - read it and pass it to the script (clamp to a minimum of 1 if the counter is missing or 0, and let an explicit `SESSIONS` override win):

```bash
count=$(cline-hook retro-count --get 2>/dev/null || echo 0)
sessions=${SESSIONS:-$(( count > 0 ? count : 1 ))}
python3 "<base-dir>/extract_signals.py" --sessions "$sessions"
```

Where `<base-dir>` is the base directory shown at the top of this skill's context. Save the JSON output for the next steps.

## 2. Analyse (parallel subagents)

Fan out 3 Agent calls in parallel with the extracted JSON data. **Subagents are read-only for memory, per the standing memory.md rule - restate this explicitly in each spawn prompt.** Each agent's job is to determine the right action and hand back a proposal (what memory write, or what rule/skill/settings.json edit); it must NOT call any memory write tool (`create_entities`, `add_observations`, `set_entity_status`, `create_relations`, `vote`) or apply a source-file edit itself. The main thread performs every memory write and file edit in step 3, after a fresh read to verify each proposal against current memory state (an agent's proposal can be stale or a duplicate by the time it reports back, especially when two agents run in parallel over related material).

### Agent A: Corrections and Preferences
Give it the `corrections` array. For each correction, determine what rule or preference the user was enforcing. Group similar corrections. For each group, propose (do not perform) one of:
- A steering rule or skill addition - identify the file and suggest the addition
- A memory write - state the project scope, entity, and observation text (`user-preferences/` entity in global scope for a preference; the relevant project scope if project-specific)
- Report back: for each group, state whether it looks already captured (and where) or is a new proposal, and the exact proposed action

### Agent B: Failures and Knowledge Gaps
Give it the `retries` array. Identify, and propose (do not perform):
- Build/test failures that revealed missing setup or configuration (propose a `pattern/` or `knowledge/` entity/observation)
- Repeated failures suggesting a missing permission allowlist entry (propose settings.json changes)
- Patterns where the agent took wrong approaches repeatedly (propose rule additions)
- Report: knowledge gaps found and the exact proposed action for each

### Agent C: Session Health and Workflow
Give it `long_sessions` and `tool_patterns`. Identify:
- Why long sessions were long (check titles/projects for context)
- Heavy tool usage that suggests missing shortcuts or automation
- Whether subagent usage was effective or could be improved
- Report: session health summary and workflow suggestions (propose any rule edit rather than applying it)

## 3. Synthesise, persist, and report to user

Once all subagents report back, the main thread applies the memory writes and file edits it agrees with (re-reading the target entity/file first to check the proposal is still accurate and non-duplicate), then compiles a summary and **shows it to the user**. This is the primary output of the skill - the user must see what was found and what actions were taken:

- Number of sessions analysed
- **Gaps closed**: corrections that were NOT previously captured but are now persisted (most important - show what was learned)
- **Already captured**: corrections that matched existing rules/memory (brief count)
- Any rule/skill file changes proposed (show the diff or addition)
- Session health observations (long sessions, workflow suggestions)
- Suggested next actions

## 4. Reset counter

```bash
cline-hook retro-count --reset
```
