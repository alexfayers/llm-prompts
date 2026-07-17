---
requires_env: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
---

# Agent teams: coordinate through the team, not just the main thread

This file only applies when the agent-teams feature is enabled - it covers direct `SendMessage` between named teammates and the shared task list, both of which require `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`. For model-tier selection and delegating complex thought to subagents (which apply regardless of this feature), see `delegation.md`.

## Let the team talk to each other

Named agents can `SendMessage` each other directly, not only the main thread - use this. Once an Opus agent has designed an approach, it (or the main thread) can hand pieces of the work straight to the named Sonnet agents via `SendMessage` rather than every result bouncing back through the main thread first. A Sonnet agent that hits something requiring real judgment should `SendMessage` the Opus delegate directly to resolve it, instead of surfacing it to the main thread to relay. Keep the main thread as the coordinator that spins the team up and checks final results, not a mandatory hop for every message between team members.

## Coordinate through the shared task list

Default to the shared task list (`TaskCreate`) for delegated work, and start early - the moment a task looks like it will involve more than one independent piece of work, create the tasks you already know about rather than waiting until the full scope is clear or hand-assigning work turn by turn:

- **Prep the roster before the task list is fully populated.** Spawn named teammates for the roles you expect to need as soon as delegation looks likely, even if some don't have a claimable task yet - a standing team can self-claim the instant new tasks land, instead of the main thread scoping everything first and only spinning people up once assignments are final.
- Break the work into tasks sized for one team member each. Use `TaskUpdate`'s `addBlockedBy`/`addBlocks` for real sequencing dependencies - a blocked task cannot be claimed until its blockers complete, so the team self-sequences without you polling.
- **Explicitly assign Opus-tier tasks.** Set `owner` on any task requiring design, root-cause work, or judgment (via `TaskUpdate`) so it cannot be accidentally self-claimed by a mechanical Sonnet worker. Leave mechanical Sonnet-tier tasks unowned so any free Sonnet team member can self-claim the next one via `TaskList`/`TaskUpdate`.
- Team members should check `TaskList` for the next unowned, unblocked task after finishing their current one, rather than going idle and waiting to be told. This is what lets the team pick up appropriate work automatically instead of bottlenecking on the main thread.
- **Claiming is not atomic - verify it stuck before doing the work.** Two idle teammates can see the same task unowned at the same instant and both call `TaskUpdate` to claim it; only one write survives as the recorded owner. After claiming, immediately `TaskGet`/`TaskList` the task again before starting any work. If the owner field names someone else, you lost the race: do not do the work anyway - `SendMessage` the teammate who won to confirm they're on it (or check with the lead if ownership is unclear), then move on to the next unowned task instead.
- **Don't be afraid to grow the team mid-task.** If the task list reveals more independent work than the current roster can move through, or a new piece of work shows up that doesn't fit any existing member's role, spawn another named team member rather than queuing everything behind the ones you already have. An idle Sonnet worker with a backlog of unclaimed tasks is a sign to add another Sonnet member, not to make it work through the backlog serially.

## Rotate team members whose context is filling up

If you are a team member and a context-usage nudge fires on you, do not just keep working degraded. `SendMessage` the lead: report that your context is getting high, hand off the state of your current task (what's done, what's left, any findings so far), and ask to be shut down. The lead should then spawn a fresh replacement team member for that role, seeded with the handed-off state, rather than letting a high-context member push on with softened accuracy. A short-lived replacement with full focus beats one worn-out member limping through the rest of the task list.
