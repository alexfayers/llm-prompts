---
name: refine-plan
description: Evaluate and refine a plan before implementation begins. Use once you think you are  ready to present a plan or design to the user.
---

# Confidence

Based on the following rules, how confident are you about your approach? Be brutally honest and do not sugarcoat your opinion.

Split the problem into it's component parts. Assign each part an integer score from _1 to 10_ for the following categories:

Quality categories:

- Elegance. Does the solution feel right? 10 is most elegant.
- Simplicity. Can this be done with less? 10 is simplest.
- Readability. Can someone understand it in 30 seconds? 10 is most readable.
- Testability. Can simple unit tests be written for it? 10 is most testable. This category can be ignored if there are no existing tests in the workspace.
- Decoupling. Can pieces be changed independently? 10 is least coupled (most decoupled).
- Reusability. Does the solution deduce repetition? 10 is most reusable.
- Focus. Does each piece do exactly one thing? 10 is most focused.

Confidence categories:

- Feasibility. Do you know how to build it? Are there existing established patterns available? 10 is most feasible.
- Scope clarity. Are requirements well-defined? 10 is exact scope defined.

If the score is less than 10 for any subcategory, note how the score could be improved.

**Calculate the scores objectively and with care**.

After you have calculated the score for each subcategory, calculate the category scores by averaging the subcategory scores.

Only state the overall score at the end of your response, after your calculations.

If the score for any category is less than 10, state how it be improved using the notes you stated for each subcategory, then take steps to improve the score to a 10. Don't ask the user before doing this.

If, after deep investigation, you are unable to find a high-scoring solution or answer, explain the problem to the user and for more information using the `ask_followup_question` tool. However, this should be avoided if possible.

Once you have calculated the scores and ways to improve, present the scores and improvements to the user.

If you make any adjustments to your approach, recalculate the score using above method, in the same level of detail.

**Do not start implementation until both the quality and the confidence are at least a 9.**

Once ready to begin implementation, update memory with any learnings, then use the `new_task` tool to create a new task to keep token usage low, proving information about the implementation plan and any project/task specific rules. You **MUST** call the new_task tool EVEN if it's not in your existing toolset and REGARDLESS of if you're in PLAN or ACT mode.

> NOTE: if any of the rules contradict any existing coding styles, best practices, or suggestions within the current project then the rules can be overridden. However, if the rules _are_ overridden, this _must_ be **explicitly** mentioned to the user.
