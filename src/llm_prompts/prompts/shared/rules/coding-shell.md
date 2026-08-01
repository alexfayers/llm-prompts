---
description: Shell-specific coding guidelines
copilot_apply_to: '**'
kiro_inclusion: fileMatch
kiro_file_match_pattern: '**/*.sh, **/*.bash, **/*.zsh'
---

# Shell coding guidelines

- Do not prepend terminal command batches with `set -e`.
- NEVER use the `-f` flag with the `rm` command. It is too high risk.
- NEVER use `rm -rf`. Use `rm -r` instead.
- NEVER kill processes by port number (e.g. `kill $(lsof -ti:PORT)`). This can kill unrelated processes (e.g. VS Code extensions). Always kill by specific PID instead.
