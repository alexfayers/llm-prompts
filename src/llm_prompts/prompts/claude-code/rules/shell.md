# Shell

- The Bash tool's working directory PERSISTS across separate command invocations. A relative path in a later command can silently resolve against a directory an earlier `cd` left you in, producing a false result that looks like a real bug (a "file not found", or a diff/compare that reports spurious differences or false matches). For any cross-tree comparison, verification, or file check, use absolute paths or `cd` to a known root within the same command - never assume you are at the repo root.
