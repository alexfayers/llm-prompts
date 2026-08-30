---
name: tidy-code
description: "Reduce code in a changeset or file - remove duplication, dead code, redundancy, and verbosity - while preserving behaviour. Use when asked to tidy, shrink, deduplicate, DRY up, or simplify code."
---

# Tidy Code

**Goal: fewer lines, identical behaviour.** Every accepted change MUST delete more than it adds - dead code, unused params/imports, redundant branches, verbose constructs count. MUST NOT alter behaviour; a behaviour change is a separate task (TODO, leave out).

## When to use

- Tidy, shrink, reduce, deduplicate, DRY up, consolidate, or simplify code.
- Dead code, copy-paste, or boilerplate that could collapse.
- A commit just made bloated a file.

NOT for bug hunting (`cr-review`). A redesign is in scope ONLY if simpler AND byte-identical - no abstraction, no behaviour change.

## Scope first

Scope used:

- **Changeset** (default): `git -P diff` plus `git -P diff @{u}..`.
- **File/module**: when named.
- **Wider**: only if explicitly asked - higher risk, more verification.

Minimal, no unrelated reformatting.

## Workflow

1. **Gather target code** per scope; read for conventions (naming, error handling, types); match existing style.

2. **Find reductions via parallel read-only subagents**, one per category, one message:
   - **Dead/unreachable code**: unused functions, params, imports, variables, unreachable branches, commented-out blocks.
   - **Verbatim repeats**: identical expression/statement/idiom/literal repeated, even one line, cross-file. Not "similar" - identical text.
   - **Duplication**: near-identical blocks differing only by a few values (method, key, message) - extractable into a helper/generator/constant/data-driven loop.
   - **Redundancy/verbosity**: needless intermediate variables, redundant conditionals, manual loops -> comprehensions/builtins, repeated literals -> one constant.
   - **Structural collapse**: parallel if/elif arms or dict lookups varying by one value, repeated dict/record construction, boilerplate a small abstraction erases.

   Each agent: read-only, candidates only - file+line ranges, exact grepped count (never an estimate), lines-removed estimate, invariant vs varying parts, behaviour-preserving confidence. Main thread merges, dedupes, ranks by lines-removed; skip fan-out on a trivial scope. Do not merge blocks that only look alike.

   Apply edits one at a time - never parallel writers; worktree isolation doesn't help - it lacks `build`/`env` symlinks. One edit -> one test run -> one commit.

3. **Apply highest-value reductions first, one at a time** - most lines for least complexity. For duplication, use the lightest abstraction (parameter > generator > data-driven lookup > constant); confirm a new param is used; reuse an existing abstraction over recreating it. Add imports with the code using them; keep edits revertible.

4. **Prove behaviour is unchanged.**
   - Existing tests MUST pass unmodified - editing a test to pass means behaviour changed; stop and reconsider.
   - Preserve tests asserting call counts, ordering, side effects.
   - Build and run the full suite (`pre-implementation`, project build skill); linting/formatting MUST pass.

5. **Gate: diff MUST be net-negative, or net-neutral with a clear maintainability win.**

   ```bash
   python3 "<base-dir>/check_reduction.py" [range]
   ```

   `range`: optional commit range (e.g. `@{u}..`), default working tree vs `HEAD`. JSON output: `added`, `removed`, `net`, `pass`, `reason`; non-zero exit past the +5-line neutral band. `pass: true` with `net` <= 0 clears outright.
   - **Neutral-cost exception**: `net` 1-5 clears only with an obvious structural win; else fail, revert.
   - **Hard rejects**: net-positive (>~5 lines), any behaviour change, or an abstraction that doesn't simplify call sites - revert.
   - Duplication needs 3+ sites to pay for a helper (verbatim repeats: net-negative at 4+, grepped count). Nothing qualifies -> "left as-is"; report lines removed vs added and, for neutral-cost changes, the specific win.

6. **Commit** per repo style and `git-usage`. One coherent reduction = one commit (or amend an unpushed/unapproved commit it belongs to).

## Anti-patterns and gotchas

- **Break-even extraction**: a helper costing as many lines as it saved - revert.
- **Hasty abstraction**: merging blocks that share syntax, not meaning, diverges into flag tangles - leave separate when unsure.
- **Behaviour drift**: silently changing an error message, default, or edge case "while tidying" - keep byte-identical; route real changes separately.
- **Flag-driven helpers**: boolean params switching between two unrelated paths - two functions in one.
- **Over-parameterising**: passing values that are always the same constant - inline them.
- **Golfing**: shrinking lines by harming readability - fewer lines must also be clearer.
- **Scope creep**: reformatting or "improving" code outside the reduction addressed.
- **Verify introduced type names exist** in the installed stub/library version - grep the stub or reuse an imported type.
- **Dead code may still be depended on** - before deleting an "unused" symbol, check it isn't re-exported, referenced by string, or public API; grep the whole package.
