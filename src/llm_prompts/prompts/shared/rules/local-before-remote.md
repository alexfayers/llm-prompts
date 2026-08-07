---
description: Check memory and known targets before guessing - ask the user rather than run broad local or web searches
copilot_apply_to: '**'
---

# Local before remote

**Before running any search, check whether the answer is already visible in the current context.** A skill's own preamble (e.g. a "Base directory for this skill: ..." header), a prior tool result from earlier in the same turn, or an explicit path/value already stated in the instructions you are following is not a lookup target - it is the answer. Use it directly instead of running `find`/`grep`/`ls` (or any broader search) for something already in front of you. Check the visible context first, before memory, before a "known target" lookup, before anything else.

**Before searching for anything you don't already know, check memory first.** Search project and global memory (per `memory.md`) for this exact question before any other lookup - a prior session may have already answered it, including one where the user told you exactly where to look.

**If memory has nothing and the answer is a known target, resolve it directly - no need to ask.** A known target (per `delegation.md`) is a specific file you already know is relevant, a tool's own `--help`/`man` page, a symbol in the current codebase, or a specific doc/URL you already know is authoritative. These are cheap, bounded lookups - just do them.

**If memory has nothing and the answer is not a known target, ask the user where to look before searching anywhere else.** Do not guess by launching a broad local search (`find` across unrelated directories, grepping the whole filesystem, walking directories you have no reason to think are relevant) and do not reach for public web search either - both are the same mistake, just aimed at different targets. The user often knows the actual best source (an internal tool, a specific doc, a team convention) that a blind search would never surface, and asking costs one turn against the many an unguided search can burn.

**Persist the answer to memory once resolved** - whether it came from the user's pointer or a bounded direct check - so the same question is answered from memory next time instead of asked or searched for again. Follow `memory.md`'s entity/observation conventions.

**Memory can be stale - treat what it says as a strong prior, not a verified fact, especially for factual/informational content.** A `user-preferences` entity (how the user likes to work) rarely changes and can generally be trusted as-is. A `pattern`/`knowledge` entity pointing at a source of information (a file path, an API, a tool's behavior, a config value) records what was true when it was written - the actual source may have moved or changed since. Where the cost of being wrong is non-trivial (an action you're about to take, a claim you're about to state as fact), verify the memory-recorded source before relying on it - a cheap way to do this without burning main-thread turns is a small delegate (Haiku-tier per `delegation.md`, since this is a known-target lookup) sent to confirm the specific fact against the live source. If it conflicts with what you observe live, do not silently pick one - surface the discrepancy to the user rather than quietly overriding either side, per `verify-before-acting.md`'s rule on inferred vs. verified claims.

**Public web search requires one of: the user's explicit direction, memory already recording the web as the right source for this, or the user naming the web as the place to look when you asked.** Don't default to it unless the user has told you to.

**When delegating a lookup to a subagent (per `delegation.md`), resolve the source yourself first via the steps above** - memory, then a known target, then asking the user if neither applies - before spawning anything. A delegate should receive an already-resolved source in its spawn prompt, never an open question you haven't resolved yourself.
