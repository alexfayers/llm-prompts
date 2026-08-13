---
description: Do not pre-validate commands or approaches the user explicitly specifies
copilot_apply_to: '**'
---

# Trust explicit user instructions

When the user explicitly tells you to run a specific command or use a specific approach, execute it directly. Do not first check its validity (looking up flags, dry-running it, sanity-checking syntax) unless the user asks you to check it first - they are capable and already exercised their own judgment in specifying it.

This does not relax any existing safety gate (destructive/irreversible actions, production changes, git push confirmation, etc.) - it only removes the "let me verify this is right first" step for otherwise-permitted execution of what was explicitly requested. If running it surfaces a real error, handle that as normal per `stop-on-fail.md`.
