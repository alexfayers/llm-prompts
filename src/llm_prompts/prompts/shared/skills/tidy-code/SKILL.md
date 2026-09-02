---
name: tidy-code
description: "Reduce code in a changeset or file - remove duplication, dead code, redundancy, and verbosity - while preserving behaviour. Use when asked to tidy, shrink, deduplicate, DRY up, or simplify code."
---

# Tidy Code

**Goal: fewer lines, identical behaviour.** Every accepted change MUST delete more than it adds. MUST NOT alter behaviour; a behaviour change is a separate task (TODO, leave out).

## When to use

- Tidy, shrink, reduce, deduplicate, DRY up, consolidate, or simplify code.
- Dead code, copy-paste, or boilerplate that could collapse.
- A commit just made bloated a file.

MUST NOT bug-hunt (`cr-review`). A redesign is in scope ONLY if simpler AND byte-identical - no abstraction, no behaviour change.

## Scope first

Scope used:

- **Changeset** (default): `git -P diff` plus `git -P diff @{u}..`.
- **File/module**: when named.
- **Wider**: MUST be explicitly asked - higher risk, more verification.

MUST be minimal, no unrelated reformatting.

## Workflow

1. **Gather target code** per scope; MUST read for conventions (naming, error handling, types); match existing style.

2. **Find reductions via parallel read-only subagents**, one per category, one message:
   - **Dead/unreachable code**: unused functions, params, imports, variables, unreachable branches, commented-out blocks.
   - **Verbatim repeats**: identical expression/statement/idiom/literal repeated, even one line, cross-file.
   - **Duplication**: near-identical blocks differing only by a few values (method, key, message) - extractable into a helper/generator/constant/data-driven loop.
   - **Redundancy/verbosity**: needless intermediate variables, redundant conditionals, manual loops -> comprehensions/builtins, repeated literals -> one constant.
   - **Structural collapse**: parallel if/elif arms or dict lookups varying by one value, repeated dict/record construction, boilerplate a small abstraction erases.

   Each agent: read-only, candidates only - file+line ranges, exact grepped count (MUST NOT estimate), lines-removed estimate, invariant vs varying parts, behaviour-preserving confidence. Main thread merges, dedupes, ranks by lines-removed; MAY skip fan-out on a trivial scope. MUST NOT merge blocks that only look alike.

   MUST apply edits one at a time - one edit -> one test run -> one commit. MUST NOT write in parallel; worktree isolation is no substitute (no `build`/`env` symlinks).

3. **Apply highest-value reductions first, one at a time** - most lines for least complexity. For duplication MUST use the lightest abstraction (parameter > generator > data-driven lookup > constant); confirm a new param is used; reuse an existing abstraction over recreating it. MUST add imports with the code using them; keep edits revertible.

4. **Prove behaviour is unchanged.**
   - Existing tests MUST pass unmodified - editing a test to pass means behaviour changed; MUST stop and reconsider.
   - MUST preserve tests asserting call counts, ordering, side effects.
   - MUST build and run the full suite (`pre-implementation`, project build skill); linting/formatting MUST pass.

5. **Gate: diff MUST be net-negative, or net-neutral with a clear maintainability win.**

   ```bash
   python3 "<base-dir>/check_reduction.py" [range]
   ```

   `range`: optional commit range (e.g. `@{u}..`), default working tree vs `HEAD`. JSON output: `added`, `removed`, `net`, `pass`, `reason`; non-zero exit past the +5-line neutral band. `pass: true` with `net` <= 0 clears outright.
   - **Neutral-cost exception**: `net` 1-5 clears only with an obvious structural win; else MUST revert.
   - **Hard rejects**: net-positive (>~5 lines), any behaviour change, or an abstraction that doesn't simplify call sites - MUST revert.
   - Duplication REQUIRES 3+ sites to pay for a helper (verbatim repeats: net-negative at 4+, grepped count). Nothing qualifies -> "left as-is"; MUST report lines removed vs added and, for neutral-cost changes, the specific win.

6. **Commit** per repo style and `git-usage`. One coherent reduction = one commit (or amend an unpushed/unapproved commit it belongs to).

## Anti-patterns and gotchas

- **Break-even extraction**: a helper costing as many lines as it saved - MUST revert.
- **Hasty abstraction**: merging blocks that share syntax, not meaning - MUST leave separate when unsure.
- **Behaviour drift**: silently changing an error message, default, or edge case "while tidying" - MUST keep byte-identical; route real changes separately.
- **Flag-driven helpers**: boolean params switching between two unrelated paths - two functions in one.
- **Over-parameterising**: passing values that are always the same constant - MUST inline them.
- **Golfing**: shrinking lines by harming readability - fewer lines MUST also be clearer.
- **Scope creep**: reformatting or "improving" code outside the reduction addressed.
- **MUST verify introduced type names exist** in the installed stub/library version - grep the stub or reuse an imported type.
- **Dead code may still be depended on** - before deleting an "unused" symbol, MUST check it isn't re-exported, referenced by string, or public API; grep the whole package.
