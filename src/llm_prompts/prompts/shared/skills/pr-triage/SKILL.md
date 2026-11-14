---
name: pr-triage
description: List open pull requests that are ready and have no unresolved review threads, marked addressed or to review. Use when triaging PRs.
---

# pr-triage

- MUST run `llm-prompts watch gh-triage [owner/repo ...] --until update --timeout 0` (default: current repo) and show its output verbatim. Exit 124 is expected.
- MUST NOT reword, reorder or filter the output.
- The command excludes draft PRs and PRs with an unresolved review thread.
- The command ignores reviews and comments starting with `[LLM]`.
- `✅ addressed:` - you authored a review or thread and every thread is resolved.
- `👀 to review:` - you have not reviewed it.
