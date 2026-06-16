---
name: refine-plan
description: Evaluate and refine a plan before implementation begins. Use once you think you are  ready to present a plan or design to the user.
---

# Refine Plan

Score the plan objectively across quality and confidence dimensions. Be brutally honest and do not sugarcoat your opinion.

Split the problem into its component parts. Assign each part an integer score from 1 to 10 for each category below. **Calculate the scores objectively and with care.**

## 1. Score each category (1-10)

**Quality:**
- `elegance` - Does the solution feel right? 10 is most elegant.
- `simplicity` - Can this be done with less? 10 is simplest.
- `readability` - Can someone understand it in 30 seconds? 10 is most readable.
- `testability` - Can simple unit tests be written for it? 10 is most testable. This category can be ignored if there are no existing tests in the workspace.
- `decoupling` - Can pieces be changed independently? 10 is least coupled.
- `reusability` - Does the solution reduce repetition? 10 is most reusable.
- `focus` - Does each piece do exactly one thing? 10 is most focused.

**Confidence:**
- `feasibility` - Do you know how to build it? Are there existing patterns? 10 is most feasible.
- `scope_clarity` - Are requirements well-defined? 10 is exact scope defined.

For any score below 10, note how it could be improved.

## 2. Validate with script

Run the scoring script with your scores and evidence. Pipe the JSON via stdin rather than passing it as a shell argument - inline single-quoted JSON breaks on apostrophes in evidence strings (e.g. "doesn't") and on newlines:

```bash
python3 "<base-dir>/score.py" <<'JSON'
<json>
JSON
```

The JSON must contain:
- `scores`: category -> integer 1-10
- `evidence`: category -> concrete citation (required for scores >= 7). Must reference a specific file path, pattern, or verifiable finding.
- `testability_skipped`: true (optional, if no tests exist)

The script rejects scores >= 7 without evidence. This forces actual research before claiming high scores. Present the full output to the user.

## 3. Validate evidence (if Agent tool available)

Launch a validation Agent with ONLY the evidence strings and scores:

> Verify these claims. For each, read the cited file/pattern/resource and confirm or dispute. Be skeptical - 9+ means near-perfect, which is rare.
>
> 1. [category]: [score] - "[evidence]"
> ...

If the validator disputes any score, lower it and re-run the script. Skip this step if the Agent tool is unavailable.

## 4. Gate and iterate

- **`pass: false`**: improve the plan to address below-threshold categories, re-score ALL categories, and re-run the script. Do not ask the user before improving - just do it. Repeat until the gate passes.
- **`pass: true`**: present the scores and plan to the user.

If you cannot reach a passing score after deep investigation, {{TOOL_ASK}}.

**Do not start implementation until both quality and confidence averages >= 9.**

Once passing, update memory with any learnings from the refinement process.

{{TOOL_WRAP_UP}}

> NOTE: if any of the rules contradict existing coding styles or best practices in the current project, they can be overridden - but this _must_ be **explicitly** mentioned to the user.
