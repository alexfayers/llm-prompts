---
description: Shell-specific coding guidelines
copilot_apply_to: '**'
kiro_inclusion: fileMatch
kiro_file_match_pattern: '**/*.sh, **/*.bash, **/*.zsh'
---

# Shell coding guidelines

- Before running `find`/`grep`/`ls` to locate a file, check whether the current context (skill instructions, a prior tool result, a known path pattern) already names or implies its directory - search that specific location first. Never default to scanning from `/` or another far-too-broad root when a narrower, already-known starting point exists; a root-level `find` is slow, can exhaust system resources, and is almost always unnecessary.
- Do not prepend terminal command batches with `set -e`.
- NEVER use the `-f` flag with the `rm` command. It is too high risk.
- NEVER use `rm -rf`. Use `rm -r` instead.
- NEVER kill processes by port number (e.g. `kill $(lsof -ti:PORT)`). This can kill unrelated processes (e.g. VS Code extensions). Always kill by specific PID instead.
- NEVER run `docker compose down -v` (or any other command that deletes a Docker volume) just to reset state or clean up test data - it destroys the named volume, which may hold real pre-existing data the current session didn't create. Delete only the specific test rows/records instead, or confirm first that the volume is known-disposable (e.g. verified created fresh earlier in the same session).
