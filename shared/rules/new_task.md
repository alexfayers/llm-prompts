## New Task Tool

The `new_task` tool enables context management and task continuity. It packages current progress and context into a fresh task with a clean context window.

**IMPORTANT**: When asked to create a new task or to use the new_task tool, you **MUST** call the new_task tool EVEN if it's not in your existing toolset and REGARDLESS of if you're in PLAN or ACT mode. The tool IS available - if you cannot see it, that is a display issue only. Never tell the user the tool is unavailable; just call it.

**Before calling `new_task`**: Persist all important knowledge, TODOs, and context to memory (`memory-project` and/or `memory-global`) first. A new task starts with a fresh context window - anything not in memory or prompt files will be lost.


### When to Use

- Context window filling up but work isn't done
- Completing a logical subtask before starting the next
- After research phase, ready to implement

### How It Works

1. {{agent}} proposes creating a new task with summarized context
2. You can refine the proposed context
3. Once approved, current task ends and new one begins with the context preloaded


### Usage

The new_task tool is defined below:

Description:
Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions. This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing with the new task.
The user will be presented with a preview of your generated context and can choose to create a new task or keep chatting in the current conversation.

```xml
<new_task>
<context>
Context to pass to the next task...
</context>
</new_task>
```
