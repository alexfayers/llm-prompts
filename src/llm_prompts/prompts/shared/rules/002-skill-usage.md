# Skill usage (HIGHEST importance)

## Session Start

At the start of every new conversation, you **MUST** use the `session-start` skill before responding to the user's first message. This is a mechanical trip-wire, not a judgment call: your first tool call in a new conversation MUST be invoking `session-start` - before any file read, edit, search, or other tool use, even when the user's request seems to point straight at a specific file or action. Jumping straight to the obvious-looking task is the exact failure this rule exists to prevent.

## Planning

Once you have planned out your implementation for a task and BEFORE showing the results to the user (such as when you {{PLAN_MODE_RESPOND_TOOL}}), **ALWAYS** use the `refine-plan` skill to further refine your plan. You _can_ call multiple tools in a single response in this case. You should do this multiple times in a session - whenever you present a plan, refine it!

## Implementation

Before you begin the implementation (when the user switches to {{ACT_MODE}}), you **MUST** use the `pre-implementation` skill to gain further insight into the correct implementation workflow before beginning your implementation.

## TDD

When writing code (new features, bug fixes, tests), you **MUST** load the `tdd` skill before writing any test or implementation code. Follow its vertical-slice workflow (one test -> one implementation -> repeat). Do NOT batch all tests first then implement - this produces low-quality tests coupled to imagined behavior.

## Session End

Before you {{TOOL_COMPLETE}} or end a conversation, you **MUST** use the `session-end` skill to ensure nothing is lost. This includes ANY response where you indicate work is finished, such as "all done", "nothing else outstanding", or similar wrap-up language, **and any moment you internally conclude that all work is complete** - even if the user hasn't explicitly asked you to wrap up. **Load and run the skill BEFORE giving any wrap-up summary.**

User signals that trigger session-end: "anything else?", "that's it", "thanks", "we're done", "wrap up", or any question implying the task is finished. When you see these, run the skill FIRST, then respond.

## Git

You MUST use the `git-usage` skill before interacting with git in **ANY** way. This includes running ANY `git` command.

## Handoff pickup

If a `HANDOFF.md` file is present in the current workspace at session start, or the user points you at a handoff doc (their own or another agent's), you **MUST** use the `pickup` skill before doing anything else with it - including before reading it in full or deciding it's stale. Do not re-verify claims the handoff or memory already states as fact; that is the specific failure `pickup` exists to prevent.

---

IMPORTANT: If you forget to follow any of these skill usage rules, there may be substantial consequences.
