---
name: refine-plan
description: Evaluate and refine a plan before implementation begins. Use once you think you are  ready to present a plan or design to the user.
---

# Refine Plan

MUST score the plan objectively across quality and confidence dimensions. MUST be brutally honest and MUST NOT sugarcoat.

MUST split the problem into component parts. MUST assign each part an integer score from 1 to 10 per category below. **MUST calculate scores objectively and with care.**

## 1. Score each category (1-10)

**Quality:**
- `elegance` - Does the solution feel right? 10 is most elegant.
- `simplicity` - Can this be done with less? 10 is simplest.
- `readability` - Can someone understand it in 30 seconds? 10 is most readable.
- `testability` - Can simple unit tests be written for it? 10 is most testable. MAY be ignored where the workspace has no tests.
- `decoupling` - Can pieces be changed independently? 10 is least coupled.
- `reusability` - Does the solution reduce repetition? 10 is most reusable.
- `focus` - Does each piece do exactly one thing? 10 is most focused.

**Confidence:**
- `feasibility` - Do you know how to build it? Are there existing patterns? 10 is most feasible.
- `scope_clarity` - Are requirements well-defined? 10 is exact scope defined.

For any score below 10, MUST note how to improve it.

## 2. Validate with script

MUST run the scoring script with your scores and evidence. MUST pipe the JSON via stdin, not as a shell argument - inline single-quoted JSON breaks on apostrophes (e.g. "doesn't") and newlines:

```bash
python3 "<base-dir>/score.py" <<'JSON'
<json>
JSON
```

The JSON MUST contain:
- `scores`: category -> integer 1-10
- `evidence`: category -> concrete citation (REQUIRED for scores >= 7). MUST reference a specific file path, pattern, or verifiable finding.
- `testability_skipped`: true (optional, if no tests exist)

The script rejects scores >= 7 without evidence. This forces actual research before claiming high scores. MUST present the full output to the user.

## 3. Validate evidence (if Agent tool available)

MUST launch a validation Agent with ONLY the evidence strings and scores:

> For each claim, MUST read the cited file/pattern/resource and confirm or dispute. MUST be skeptical - 9+ means near-perfect and is rare.
>
> 1. [category]: [score] - "[evidence]"
> ...

If the validator disputes any score, MUST lower it and re-run the script. MAY skip where the Agent tool is unavailable.

## 4. Gate and iterate

- **`pass: false`**: MUST improve the plan to address below-threshold categories, re-score ALL categories, and re-run the script. MUST NOT ask the user before improving. MUST repeat until the gate passes.
- **`pass: true`**: MUST present the scores and plan to the user.

If you cannot reach a passing score after deep investigation, {{TOOL_ASK}}.

**MUST NOT start implementation until both quality and confidence averages >= 9.**

Once passing, MUST update memory with learnings from the refinement.

{{TOOL_WRAP_UP}}

> NOTE: if any of the rules contradict existing coding styles or best practices in the current project, they MAY be overridden - but this MUST be **explicitly** mentioned to the user.
