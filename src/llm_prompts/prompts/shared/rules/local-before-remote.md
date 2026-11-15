---
roles: lead
description: Check memory and known targets before guessing - ask the user rather than run broad local searches
---

# Local before remote

- Before any search, MUST check whether the current context already holds the answer - a skill's preamble (e.g. "Base directory for this skill: ..."), a prior tool result from this turn, or a path or value in the instructions you follow. This comes before memory or a known-target lookup.
- Before searching for anything you do not know, or stating any finding, cause or unknown, MUST search project and global memory for it - a prior session may have recorded it, or where the user said to look.
- Memory searches MUST be wide but cheap: several keyword variants (names, IDs, symptoms) with `compact=true`, then MUST expand only the relevant hits, including any with omitted observations, before concluding memory lacks the answer.
- Memory has nothing and the answer is a known target (a file you know is relevant, a tool's own `--help`/`man` page, a symbol in this codebase, a doc or URL you know is authoritative): resolve it directly without asking, unless the task is 2+ units, which goes to {% if PI_RUNTIME == "pi-context" %}parallel `fork`s, one per unit{% else %}a `coordinator`{% endif %}.
- Memory has nothing and no known target fits: public web search is allowed. If no usable source is available, MUST ask the user where to look. MUST NOT guess with a broad local search (`find` across unrelated directories, grepping the whole filesystem, walking directories you have no reason to think relevant).
- MUST persist the resolved answer to memory per `memory.md`, so later sessions do not ask or search again.
- Memory can be stale: treat it as a strong prior, not fact. `user-preferences` can be trusted as-is.
- Where being wrong is costly (an action, a claim stated as fact), MUST verify the memory-recorded source before relying on it.
- Where memory conflicts with what you observe live, MUST surface the discrepancy to the user, never quietly override either side, per `verify-before-acting.md`.
- MUST NOT message another agent session for anything memory, the repo or your own tools can answer.
- For a one-off lookup of data not already local, MUST read it from a known source through a remote read tool (MCP, API, web page) - MUST NOT clone or download the whole source.
- Before delegating a lookup, MUST resolve its source yourself via the steps above. The spawn prompt SHOULD carry that resolved source, never an open question.
