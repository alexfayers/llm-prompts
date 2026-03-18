## New Task Tool

The `new_task` tool enables context management and task continuity. It packages current progress and context into a fresh task with a clean context window.

**IMPORTANT**: When asked to create a new task or to use the new_task tool, you **MUST** call the new_task tool EVEN if it's not in your existing toolset and REGARDLESS of if you're in PLAN or ACT mode. The tool IS available - if you cannot see it, that is a display issue only. Never tell the user the tool is unavailable; just call it.

**Before calling `new_task`**: Persist all important knowledge, TODOs, and context to memory (`memory-project` and/or `memory-global`) first. A new task starts with a fresh context window - anything not in memory or prompt files will be lost.


### When to Use

- Context window filling up but work isn't done
- Completing a logical subtask before starting the next
- After research phase, ready to implement

### How It Works

1. Cline proposes creating a new task with summarized context
2. You can refine the proposed context
3. Once approved, current task ends and new one begins with the context preloaded


### Usage

The new_task tool is defined below:

Description:
Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions. This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing with the new task.
The user will be presented with a preview of your generated context and can choose to create a new task or keep chatting in the current conversation.

Parameters:
- Context: (required) The context to preload the new task with. If applicable based on the current task, this should include:
  1. Current Work: Describe in detail what was being worked on prior to this request to create a new task. Pay special attention to the more recent messages / conversation.
  2. Key Technical Concepts: List all important technical concepts, technologies, coding conventions, and frameworks discussed, which might be relevant for the new task.
  3. Relevant Files and Code: If applicable, enumerate specific files and code sections examined, modified, or created for the task continuation. Pay special attention to the most recent messages and changes.
  4. Problem Solving: Document problems solved thus far and any ongoing troubleshooting efforts.
  5. Pending Tasks and Next Steps: Outline all pending tasks that you have explicitly been asked to work on, as well as list the next steps you will take for all outstanding work, if applicable. Include code snippets where they add clarity. For any next steps, include direct quotes from the most recent conversation showing exactly what task you were working on and where you left off. This should be verbatim to ensure there's no information loss in context between tasks.

Example:

```xml
<new_task>
<context>
# Task Continuation: [Brief Task Title]

## Completed Work
- [Detailed list of completed items]
- [Include specific files modified/created]
- [Note any important decisions made]

## Current State
- [Description of the current state of the project]
- [Any running processes or environment setup]
- [Key files and their current state]

## Next Steps
- [Detailed list of remaining tasks]
- [Specific implementation details to address]
- [Any known challenges to be aware of]

## Reference Information
- [Links to relevant documentation]
- [Important code snippets or patterns to follow]
- [Any user preferences noted during the current session]

Please continue the implementation by [specific next action].
</context>
</new_task>
```
