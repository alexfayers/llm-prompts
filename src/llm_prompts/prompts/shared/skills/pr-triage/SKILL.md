---
name: pr-triage
description: List open pull requests that are ready and have no unresolved review threads, marked addressed or to review. Use when triaging PRs.
---

# pr-triage

- MUST run `python3 "<base-dir>/pr_triage.py" [owner/repo ...]` (default: current repo) and show its output verbatim.
- MUST NOT reword, reorder or filter the output.
- The script excludes draft PRs and PRs with an unresolved review thread.
- The script ignores reviews and comments starting with `[LLM]`.
- `✅ addressed:` - you authored a review or thread and every thread is resolved.
- `👀 to review:` - you have not reviewed it.
