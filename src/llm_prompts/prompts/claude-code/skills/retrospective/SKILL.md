---
name: retrospective
description: Analyse recent session transcripts to extract learnings, discover pain points, and persist them into memory/skills/rules. Run manually when the retrospective counter is due (session-end reminds you at 5+).
---

# retrospective

Analyse recent Claude Code sessions to surface patterns, corrections, and pain points that should become rules, memory, or skills.

## 1. Extract signals

Analyse exactly the sessions that have elapsed since the last retrospective. The session counter at `~/.claude/.retrospective-counter` tracks this - read it and pass it to the script (clamp to a minimum of 1 if the counter is missing or 0, and let an explicit `SESSIONS` override win):

```bash
count=$(cat ~/.claude/.retrospective-counter 2>/dev/null || echo 0)
sessions=${SESSIONS:-$(( count > 0 ? count : 1 ))}
python3 "<base-dir>/extract_signals.py" --sessions "$sessions"
```

Where `<base-dir>` is the base directory shown at the top of this skill's context. Save the JSON output for the next steps.

## 2. Analyse (parallel subagents)

Fan out 3 Agent calls in parallel with the extracted JSON data:

### Agent A: Corrections and Preferences
Give it the `corrections` array. For each correction, determine what rule or preference the user was enforcing. Group similar corrections. For each group:
- If a steering rule or skill should capture this, identify the file and suggest an addition
- If it is a preference, persist to memory (`user-preferences/` entity, global scope)
- If it is project-specific, persist to the relevant project scope
- Report back: for each group, state whether it was already captured or newly persisted, and what action was taken

### Agent B: Failures and Knowledge Gaps
Give it the `retries` array. Identify:
- Build/test failures that revealed missing setup or configuration (persist as `pattern/` or `knowledge/` entities)
- Repeated failures suggesting a missing permission allowlist entry (suggest settings.json changes)
- Patterns where the agent took wrong approaches repeatedly (suggest rule additions)
- Report: knowledge gaps found and how they were addressed

### Agent C: Session Health and Workflow
Give it `long_sessions` and `tool_patterns`. Identify:
- Why long sessions were long (check titles/projects for context)
- Heavy tool usage that suggests missing shortcuts or automation
- Whether subagent usage was effective or could be improved
- Report: session health summary and workflow suggestions

## 3. Synthesise and report to user

After all subagents complete, compile a summary and **show it to the user**. This is the primary output of the skill - the user must see what was found and what actions were taken:

- Number of sessions analysed
- **Gaps closed**: corrections that were NOT previously captured but are now persisted (most important - show what was learned)
- **Already captured**: corrections that matched existing rules/memory (brief count)
- Any rule/skill file changes proposed (show the diff or addition)
- Session health observations (long sessions, workflow suggestions)
- Suggested next actions

## 4. Reset counter

```bash
echo "0" > ~/.claude/.retrospective-counter
```
