---
name: ask-codex
description: Delegate to codex, a separate CLI agent running a different engine, for an independent or adversarial second opinion on a diff, plan, or piece of work. Use when you want a different model's review.
requires_command: codex
exclude_targets: codex
---

# Ask codex

Delegate a task to `codex` - a separate CLI coding agent running a different underlying engine - to get a genuinely independent perspective. The headline use is an adversarial second opinion on a diff, plan, or piece of work: a different engine catches what another Claude pass would miss.

## When to use

- The user explicitly asks for a "second opinion", to "ask codex", or for an "adversarial"/"antagonistic" review.
- Proactively before finalizing a non-trivial plan, design, or code review, when an outside check adds real value.
- To have codex run one of its own installed skills and return the result.

## Availability guard

MUST run `command -v codex` first. If it prints nothing, codex is not installed - MUST tell the user and stop. MUST NOT fabricate a review or guess what codex "would" say. The installer only warns about a stale skill link, never removes one, so this skill can outlive a codex uninstall.

## Reviewing a diff, plan, or delegating a task

MUST use the generic exec form for everything - a diff, a plan, a design doc, or a general delegated task:

```
codex exec -s read-only --skip-git-repo-check "<adversarial prompt>"
```

MUST NOT use `codex exec review`: its diff-selection flags (e.g. `--base`) are mutually exclusive with a custom prompt in current codex versions, so it cannot carry an adversarial framing alongside a diff. The generic form always composes with any prompt, regardless of the content's source.

`-s read-only` keeps codex from writing anything; `--skip-git-repo-check` lets it run from any cwd. MUST NOT pass `-m` unless the user asks for a specific model - use codex's default.

MUST pipe large content (a diff, a long plan) via stdin, not an arg, to avoid `ARG_MAX`:

```
{ printf '%s\n' "<adversarial prompt>"; git diff <range>; } | codex exec -s read-only --skip-git-repo-check -
```

MUST substitute `cat <file>` for `git diff <range>` when reviewing a plan or design doc.

## Delegate to codex's own skills

Codex receives the same shared skill set as you and has a native skills tool, so you MAY name a skill directly in the prompt:

```
codex exec -s read-only --skip-git-repo-check "Use your refine-plan skill to score this plan, then return the scored output:\n\n<plan>"
```

## Reading output & safety

- MUST read codex's stdout directly. MUST NOT use `-o <file>`.
- Where codex disagrees with your view, MUST present both to the user - MUST NOT silently pick a side.
- Codex has its own auth/config under `~/.codex`. On an auth failure, MUST tell the user to run `codex login`; MUST NOT swallow the error.
- MUST NOT use `--dangerously-bypass-approvals-and-sandbox`, `-s workspace-write`, or `-s danger-full-access`.
- A review can take a while; MUST fire a notification when it finishes, per the notify rule.

## Relationship to other skills

This skill is specifically for an *external, different-engine* take - self-scoring a plan against a rubric and interrogating the user about a design are other skills. SHOULD use it when the value is that the reviewer is not Claude.
