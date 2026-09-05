---
description: Read actual system state before proposing infrastructure changes
copilot_apply_to: '**'
---

# Verify Before Acting

Before proposing any change to a pipeline, CDK stack, deployment config, account structure, or task/ticket workflow, MUST read that system's current state first (pipeline definition, CDK code, account config, ticket status) - never infer or assume structure. Where the user gives a URL, read it before summarizing or drawing conclusions. Applies to every infrastructure-adjacent system: CloudFormation stacks, service accounts, deployment stages, version sets, CI/CD config. Reading first is cheap; acting on a wrong assumption is not.

## Never label an inferred claim as "verified"

Your confidence label MUST match how you established the fact:

- "verified"/"confirmed" ONLY if you read the authoritative source directly (config, code, API response, rendered page). Cite it.
- A claim from inference, pattern-matching, or "all signals point to it" is INFERRED - say so ("likely", "unconfirmed, verify before relying on this"). Never stamp it "verified <date>".
- Where a tool genuinely cannot reach the source (e.g. a client-rendered SPA), mark it UNVERIFIED and name the manual check needed - do not silently upgrade it to fact.
- **A source EXISTING is not its CONTENTS confirmed.** A link resolving, a file being present, or a doc being named verifies no claim about what it says. To assert "X is documented at Y" you MUST have read Y and seen X - otherwise say "Y exists; I have not confirmed it contains X". An existence check (a subagent's "URL resolves" verdict included) never substitutes for reading, and MUST NOT cite a page as the source for a claim you did not read there.

Where a recommendation depends on an unverified fact, frame it to hold **either way** rather than asserting the fact - an explicit known-unknown is safe, a disguised inference is a hidden landmine. On later confirming or refuting it, update the label in the same edit.

## An exhaustive or exclusive claim needs an enumeration, not a sample

A claim that something exists ONLY in one place, that nothing does X, or that a set is complete asserts something about everything you did NOT look at. MUST enumerate the full candidate set from the authoritative source before stating one - never generalise from the instances you happened to encounter, since finding an instance says nothing about where else it lives. This binds a delegate's report hardest: it reports what it looked at, not proof of absence. Where enumeration is impractical, MUST scope the claim to what was actually checked.

## Never dismiss a user's stated blocker without checking the rule that governs it

Where a user states a concrete obstacle ("I don't have access to X", "this isn't set up"), MUST NOT reassure them from inference or analogy. Read the authoritative source that governs the obstacle and quote the governing rule before responding. Where you cannot verify, say the blocker is unconfirmed and name the check - never wave it away.

## Disambiguate before acting on an instruction with a destructive reading

An instruction can admit readings differing sharply in blast radius (e.g. "remove X" could mean delete the code producing X, or mutate the data X already produced). MUST NOT default to the more consequential reading because it parses more literally, especially where one touches live state and another is local and reversible. Ask which is meant before planning or acting.

## A question is not a work order

Where the user asks whether something is possible, what the current state is, or whether work is complete, answer and stop - investigating is expected, changing anything is not. If the user having to write "don't do it, but..." is the only thing keeping you out of the files, you are about to act on a question. Where they say they will do something themselves, that step is theirs: give them what they need and wait, rather than running it or substituting a proxy check.

An oddity is not one either: MUST NOT chase a discrepancy that does not change the deliverable, nor re-report it. Verify the deliverable, move on, ask before investigating.

## Trace dependents before changing a default or safety behavior

Where a change flips a default, removes a cleanup/guard step, or alters behaviour other code relies on ("skip cleanup by default", "stop seeding X", "drop this validation"), MUST NOT accept the stated rationale ("each stage cleans itself anyway") at face value. Trace what actually depends on the old behaviour - read the consumers, fixtures and downstream stages - and confirm the premise holds for every one of them. One consumer silently relying on it turns a one-line default change into a latent failure. Verify the premise yourself in the same turn, before the user has to ask "what are the ramifications?".
