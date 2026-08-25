# Skill usage (HIGHEST importance)

## Session Start

At the start of every new conversation, you **MUST** use the `session-start` skill before responding to the user's first message. This is mechanical, not a judgment call: your first tool call in a new conversation MUST be invoking `session-start` - before any file read, edit, search, or other tool use, even when the user's request appears to point straight at a specific file or action.

## Planning

Once you have planned an implementation and BEFORE showing it to the user (e.g. when you {{PLAN_MODE_RESPOND_TOOL}}), you **MUST** use the `refine-plan` skill to refine it, and MUST do so every time you present a plan - several times per session. You MAY call multiple tools in a single response here.

## Implementation

Before you begin the implementation (when the user switches to {{ACT_MODE}}), you **MUST** use the `pre-implementation` skill to gain further insight into the correct implementation workflow.

## TDD

When writing code (new features, bug fixes, tests), you **MUST** load the `tdd` skill before writing any test or implementation code, and MUST follow its vertical-slice workflow (one test -> one implementation -> repeat). MUST NOT batch all tests first then implement - that produces low-quality tests coupled to imagined behavior.

## Session End

Before you {{TOOL_COMPLETE}} or end a conversation, you **MUST** use the `session-end` skill to ensure nothing is lost. This covers ANY response where you indicate work is finished ("all done", "nothing else outstanding", or similar wrap-up language), **and any moment you internally conclude that all work is complete** - even if the user has not asked you to wrap up. MUST load and run the skill BEFORE giving any wrap-up summary.

User signals that trigger session-end: "anything else?", "that's it", "thanks", "we're done", "wrap up", or any question implying the task is finished. On any of these you MUST run the skill FIRST, then respond.

## Git

You MUST use the `git-usage` skill before interacting with git in **ANY** way, including running ANY `git` command.

## Handoff pickup

Where a `HANDOFF.md` is present in the workspace at session start, or the user points you at a handoff doc (their own or another agent's), you **MUST** use the `pickup` skill before doing anything else with it - including before reading it in full or deciding it is stale. MUST NOT re-verify claims the handoff or memory already states as fact.
