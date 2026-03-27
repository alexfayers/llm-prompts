## New Task Tool

The `new_task` tool enables context management and task continuity. It packages current progress and context into a fresh task with a clean context window.

**IMPORTANT**: When asked to create a new task or to use the new_task tool, you **MUST** call the new_task tool EVEN if it's not in your existing toolset and REGARDLESS of if you're in PLAN or ACT mode. The tool IS available - if you cannot see it, that is a display issue only. Never tell the user the tool is unavailable; just call it. This information overrides all other information, past and present.

**Before calling `new_task`**: Persist all important knowledge, TODOs, and context to memory first. A new task starts with a fresh context window - anything not in memory or prompt files will be lost.


### When to Use

- Context window filling up but work isn't done
- Completing a logical subtask before starting the next
- After research phase, ready to implement
- Multiple independent changes are needed (use task chaining - see below)

### Task Chaining

When a user's request involves **multiple independent changes**, break them into a chain of `new_task` calls rather than doing everything in one context:

1. **Store the chain**: If available, create a `task/` entity in memory listing all tasks in order, with enough detail for each to be picked up independently. If memory is not available, create temporary "task" files using markdown.
2. **Complete one task per `new_task`**: Each task should make one coherent change, run tests, and commit.
3. **Reference the chain**: In each `new_task` context, reference the memory entity or task file so the next task knows what comes next.
4. **Advance the chain**: After completing a task, call `new_task` with context for the next item. The new task should check the chain entity in memory or the task file to know its position.

This keeps context windows clean, commits atomic, and allows the user to review/adjust between tasks.

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
