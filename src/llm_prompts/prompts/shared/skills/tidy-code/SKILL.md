---
name: tidy-code
description: "Reduce the amount of code in a changeset or file - remove duplication, dead code, redundancy, and over-verbose constructs - while preserving behaviour. Use when asked to tidy, shrink, deduplicate, DRY up, or simplify code."
---

# Tidy Code

**The goal is fewer lines of code with identical behaviour.** Every accepted change must delete more than it adds. Duplication extraction is one tool for that, but so are deleting dead code, dropping unused parameters/imports, collapsing redundant branches, and replacing verbose constructs with tighter equivalents. Optimise for net deletions, not for cleverness.

This is a *refactor* skill - it must not alter behaviour. If a reduction would change what the code does, it is a separate task; note it as a TODO and leave it out.

## When to use

- The user asks to tidy, shrink, reduce, deduplicate, DRY up, consolidate, or simplify code.
- You notice dead code, copy-paste, or boilerplate that could collapse.
- A commit you just made bloated a file.

Do NOT use this to hunt for bugs (use `cr-review`). Architecture redesigns ARE in scope **only** when the new structure is genuinely simpler (fewer lines, less nesting, less repetition) AND delivers byte-identical behaviour - e.g. collapsing a long if/elif dispatch chain into a lookup table. A redesign that adds abstraction, changes behaviour, or trades line-count for "cleanliness" is out of scope. When in doubt, prefer the smaller local change. Stay within the existing module's style.

## Scope first

Decide the search surface and tell the user which you are using:

- **Changeset** (default): the current diff - `git -P diff` plus `git -P diff @{u}..`.
- **File / module**: when the user names a target.
- **Wider**: only if explicitly asked - higher risk, needs more verification.

Keep the change minimal and focused. Do not opportunistically reformat unrelated code.

## Workflow

1. **Gather the target code** per the scope. Read enough surrounding context to learn the module's conventions (naming, error handling, types). Existing style overrules personal preference.

2. **Find reduction opportunities via parallel subagents.** A single pass spots one kind of waste and misses the rest, so fan out one read-only subagent per category, each hunting with a focused lens. Dispatch them in one message so they run concurrently.

   Category split (one agent each - adjust to the codebase):
   - **Dead / unreachable code**: unused functions, params, imports, variables, vars assigned-but-never-read, branches that can't execute, commented-out blocks. (Often the biggest, safest wins.)
   - **Verbatim repeats**: the *same* expression, statement, small idiom, or literal copy-pasted with **zero or near-zero variation** - even a single line, especially across files. E.g. `datetime.now(tz=timezone.utc).isoformat()...` written out at 5 call sites, or an identical `for x in [...]: with cm(...): pass` idiom at 3. These are the easiest, safest wins and the most frequently *missed* ones - a verbatim repeat is not a "block differing by a few values", so the duplication lens below walks straight past it. Hunt identical text, not just similar shapes.
   - **Duplication**: near-identical blocks differing only by a few values (API method, key, message) - extractable into one helper/generator/constant/data-driven loop.
   - **Redundancy / verbosity**: needless intermediate variables, redundant conditionals, manual loops replaceable by comprehensions/builtins, repeated literals that should be one constant.
   - **Structural collapse**: parallel `if/elif` arms or dict lookups varying by one value, repeated dict/record construction, boilerplate that a small abstraction erases.

   Strict contract for every agent: **read-only** (no edits), returns *candidates only*, and for each candidate reports - file + line ranges, an **exact occurrence count obtained by grepping the whole scope** (never an eyeballed estimate - an undercounted site is the usual reason a real net-negative win gets misjudged as break-even), the estimated **lines removed** if applied, what is invariant vs what varies (for duplication), and a confidence the change is behaviour-preserving. Tell each agent the agreed scope.

   When they return, the main thread **merges, dedupes, and ranks candidates by lines-removed**. Act on the biggest, safest wins first. If blocks only *look* alike but mean different things, do NOT merge them. For a trivially small scope, skip the fan-out and scan directly.

   > **Parallel find, sequential apply.** Fan out for *discovery* (read-only, always safe), but apply edits one at a time in the main thread - never fan out parallel writers. Edits converge (a new helper lands in one file; call sites cluster), so concurrent writers overwrite each other. Worktree isolation only moves that to a painful N-branch merge - and **does not work with build systems that wire a workspace's build directory via symlinks** (a plain `git worktree` has no `build`/`env` symlinks or build-dependency wiring, so the build/test commands can't run there). One workspace has one `build/`, so verification serializes regardless. Keep the one-edit -> one-test-run -> one-commit loop.

3. **Apply the highest-value reductions first, one at a time.** Prefer the change that deletes the most lines for the least added complexity. For duplication, pick the lightest abstraction (parameter > generator > data-driven lookup > constant); confirm any new param is actually used and the abstraction doesn't already exist (search first, reuse over re-create). Add new imports at the same time. Keep each edit independently revertible.

4. **Prove behaviour is unchanged.**
   - Existing tests MUST pass unmodified - if a test needs editing to pass, behaviour changed; stop and reconsider.
   - Watch tests asserting call counts, ordering, or side effects - preserve them exactly.
   - Build and run the full suite (follow `pre-implementation` and the project's build skill). Linting/formatting must pass.

5. **Gate: the diff must be net-negative, OR net-neutral with a clear maintainability win.** Check `git -P diff --stat` after each edit and across the whole changeset.
   - **Default bar - net-negative**: deletions exceed insertions. This is the goal for every change; a net-positive diff that is *not* obviously more maintainable is a failed tidy - **revert it**.
   - **Neutral-cost exception**: a change that is roughly break-even (within a few lines either way - say -5 to +5) is acceptable IF the new pattern is *obviously* more maintainable or elegant than the old: e.g. a long if/elif chain becoming a flat dispatch table, deeply nested conditionals becoming a guard-clause sequence, a hand-rolled loop becoming a clear comprehension. "Obviously" means a reviewer would agree at a glance, not a judgement call you have to argue for. The improvement must be in *structure*, not taste.
   - **Hard rejects regardless of elegance**: a clearly net-positive diff (more than ~5 lines added net), any behaviour change, or any "cleaner" rewrite that adds a layer of abstraction without simplifying the call sites. When the maintainability win is debatable, fall back to the net-negative bar and revert.
   - A two-occurrence short block usually won't clear even the neutral bar; duplication needs 3+ sites or long blocks to pay for a helper. **Exception - verbatim repeats:** a *zero-variation* expression or idiom (identical text, no flags, no divergence risk) collapsing into a named one-line helper or constant clears the bar at as few as 3 sites and is unambiguously net-negative at 4+ - the per-site saving may be one line, but `(N sites - 1) - (helper def)` is comfortably negative and the abstraction carries no flag-driven risk because nothing varies. Do the arithmetic with the *grepped* count, not an estimate. If nothing qualifies, the honest outcome is "left as-is" - say so; never ship a bloating refactor to look busy. Report lines removed vs added and, for any neutral-cost change, the specific maintainability win that justifies it.

6. **Commit** per the repo's style and the `git-usage` rules. One coherent reduction = one commit (or amend, per the git rules, if it cleans up an unpushed/unapproved commit it belongs to).

## Anti-patterns to avoid

- **Break-even extraction**: pulling a block into a helper whose signature + docstring + imports cost as many lines as it saved, with no structural win. If `git diff --stat` isn't net-negative and the result isn't *obviously* more maintainable (see the gate's neutral-cost exception), you just moved code and added a layer - revert.
- **Hasty abstraction**: merging blocks that share syntax but not meaning. They diverge later and the helper becomes a tangle of flags. When unsure, leave them separate.
- **Behaviour drift**: silently changing an error message, default, or edge case "while tidying". Keep behaviour byte-identical; route real changes to a separate task.
- **Flag-driven helpers**: a function with boolean params switching between two unrelated paths - that's two functions in a trench coat.
- **Over-parameterising**: passing values that are always the same constant - inline them.
- **Golfing**: shrinking lines by harming readability (nested ternaries, one-letter names, dense one-liners). Fewer lines must also be clearer, or no better.
- **Scope creep**: reformatting or "improving" code outside the reduction being addressed.

## Gotchas

- **Verify introduced type names exist.** If a change adds a type annotation, confirm the type is real in the *installed* stub/library version before relying on it - typed-stub contents (e.g. `mypy_boto3_*`) vary by version. A guessed name reads fine but fails the type checker, costing a build round-trip. Grep the stub or reuse a type the surrounding code already imports.
- **Dead code may be load-bearing.** Before deleting an "unused" symbol, check it isn't re-exported, referenced by string (getattr, config, entry points), or part of a public API. Grep the whole package, not just the file.
