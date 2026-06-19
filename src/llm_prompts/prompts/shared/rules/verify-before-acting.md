---
description: Read actual system state before proposing infrastructure changes
copilot_apply_to: '**'
---

# Verify Before Acting

Before proposing any change to a pipeline, CDK stack, deployment configuration, account structure, or task/ticket workflow, you MUST first read the current state of that system (pipeline definition, CDK code, account config, ticket status). Never propose changes based on inferred or assumed structure. When the user provides a URL to a pipeline or system, read it before summarizing or drawing conclusions.

This applies to all infrastructure-adjacent systems: pipelines, CloudFormation stacks, service accounts, deployment stages, version sets, and CI/CD configurations. The cost of reading first is low; the cost of acting on a wrong assumption is high.

## Never label an inferred claim as "verified"

When you write a fact into a plan, runbook, or doc, the confidence label MUST match how you actually established it:

- A claim is "verified" / "confirmed" ONLY if you read the authoritative source directly (config, code, API response, the rendered page). Cite that source.
- A claim you reached by inference, pattern-matching, or "all signals point to it" is INFERRED - say so explicitly ("likely", "all signals say X but unconfirmed", "verify in-browser before relying on this"). Never carry a "verified <date>" stamp onto it.
- If a tool genuinely cannot reach the source (e.g. a client-rendered SPA), mark the item UNVERIFIED and name the manual check needed - do not silently upgrade it to fact.

When a recommendation appears to depend on an unverified fact, frame the recommendation so it holds **either way** rather than asserting the fact. A plan with an explicit known-unknown is safe; a plan that disguises an inference as a verified fact is a hidden landmine. If you later confirm or refute the claim, update the label in the same edit.

## Trace dependents before changing a default or safety behavior

When a change flips a default, removes a cleanup/guard step, or otherwise alters behavior that other code relies on (e.g. "skip cleanup by default", "stop seeding X", "drop this validation"), do not accept the stated rationale ("each stage cleans itself anyway") at face value. First trace what actually depends on the old behavior: read the consumers, fixtures, or downstream stages and confirm the premise holds for every one of them. A single consumer that silently relied on the old behavior turns a one-line default change into a latent failure. Verify the premise yourself in the same turn - before the user has to ask "what are the ramifications?".
