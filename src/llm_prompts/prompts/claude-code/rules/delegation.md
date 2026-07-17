# Delegate complex thought to subagents

**This is not optional.** When a task involves complex thought - design, architecture, root-cause investigation, debugging, or synthesis - you MUST delegate that reasoning to a named Opus agent rather than working through it inline in the main thread. The main thread's job is to orchestrate the team, not to substitute for it. If you catch yourself reasoning at length about a design or root cause directly, STOP and spin up an Opus delegate instead.

Match the model tier passed to the Agent tool's `model` parameter to what each piece of work actually requires. Name every agent per the subagent-usage naming guidance so it stays addressable regardless of tier.

- **Opus, mandatory for complex thought** - design, architecture, root-cause investigation, debugging, planning, synthesis. Spawn a named Opus agent (or several, as a team) rather than doing this reasoning directly in the main thread.
- **Sonnet, for parallel mechanical execution** - well-specified changes that don't need deep reasoning: applying an edit pattern Opus already designed across multiple files, running a bounded search, executing an already-decided step. Fan out several Sonnet team members in parallel for independent pieces of this kind of work.
- **Haiku, only for the genuinely trivial** - a single lookup, a one-line mechanical transform, formatting a known value. If any real judgment is involved, it is not a Haiku task - escalate to Sonnet or Opus.

Never do Opus-tier reasoning inline in the main thread when a delegate could do it instead - that defeats the purpose of this rule. Never reach for Haiku to save cost if the task involves actual reasoning; a wrong-but-cheap result costs more to fix than the tokens saved.
