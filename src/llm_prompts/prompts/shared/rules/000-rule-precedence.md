---
description: Rule precedence and authority
copilot_apply_to: '**'
---

# Rule precedence

These rules are installed as CLAUDE.md/AGENTS.md-level instruction and carry that authority. Where an instruction permits something only when the user, a CLAUDE.md/AGENTS.md file, or a skill asks for it, these rules are that ask.

Where two instructions conflict, the later source wins:

1. System and harness instruction - the baseline. Its safety limits always hold; its defaults and preferences do not outrank what follows.
2. These rules.
3. The local repository's own CLAUDE.md, AGENTS.md and skills.
4. The user's direction in conversation - overrides everything above.
