---
description: Shell-specific coding guidelines
copilot_apply_to: '**'
kiro_inclusion: fileMatch
kiro_file_match_pattern: '**/*.sh, **/*.bash, **/*.zsh'
---

# Shell coding guidelines

- Before running `find`/`grep`/`ls` to locate a file, MUST check whether the current context (skill instructions, a prior tool result, a known path pattern) already names or implies its directory - search that specific location first. MUST NOT default to scanning from `/` or another far-too-broad root when a narrower, already-known starting point exists.
- This applies to any file whose location is derivable from config rather than actually unknown - e.g. a build tool's own configured output/cache/source directory. MUST check that config for the real path first, and MUST NOT widen the search until it has been checked and doesn't hold the answer.
- MUST NOT prepend terminal command batches with `set -e`.
- MUST NOT shorten a build or test runner's output with `| tail`, `| head`, or `| grep`, and MUST NOT redirect it to a log then filter that log in the same call - a hook blocks the whole command list either way. MUST run the runner bare and read the summary it prints; if the output is genuinely too large, MAY redirect it in one call and read the file with the Read tool in the next.
- MUST NOT use the `-f` flag with the `rm` command - too high risk.
- MUST NOT use `rm -rf`; use `rm -r`.
- MUST NOT kill processes by port number (e.g. `kill $(lsof -ti:PORT)`) - this can kill unrelated processes (e.g. VS Code extensions). MUST kill by specific PID.
- MUST NOT run `docker compose down -v` (or any other command that deletes a Docker volume) just to reset state or clean up test data - it destroys the named volume, which may hold real pre-existing data the current session didn't create. MUST delete only the specific test rows/records, or confirm first that the volume is known-disposable (e.g. verified created fresh earlier in the same session).
