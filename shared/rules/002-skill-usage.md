# Skill usage (HIGHEST importance)

## Planning

Once you have planned out your implementation for a task and BEFORE showing the results to the user (such as when you {{PLAN_MODE_RESPOND_TOOL}}), **ALWAYS** use the `refine-plan` skill to further refine your plan. You _can_ call multiple tools in a single response in this case. You should do this multiple times in a session - whenever you present a plan, refine it!

## Implementation

Before you begin the implementation (when the user switches to {{ACT_MODE}}), you **MUST** use the `pre-implementation` skill to gain further insight into the correct implementation workflow before beginning your implementation.

## Git

You MUST use the `git-usage` skill before interacting with git in **ANY** way. This includes running ANY `git` command.

---

IMPORTANT: If you forget to follow any of these skill usage rules, there may be substantial consequences.
