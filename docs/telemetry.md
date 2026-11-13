# Telemetry

Every command sends one anonymous event to PostHog (EU). llm-prompts sends, writes and prints nothing while no agents are installed. The first run with an agent installed sends nothing and prints a notice. Turn it off with `DO_NOT_TRACK=1`, `LLM_PROMPTS_NO_TELEMETRY=1`, `CI`, or `enabled = false` under `[telemetry]` in `config.toml`. `LLM_PROMPTS_TELEMETRY_DEBUG=1` prints each event and sends it before the command exits.

Each event has:

- the command and the sorted names of its flags (never their values)
- agent names, overlay count, and the version of each overlay installed from a github.com source
- tool versions before and after: the installed `commit` of a remote source, `base` (the newest `origin/main` commit the install contains), and for local checkouts `local`, `dirty` and `ahead`. A local commit not on `origin/main` is never sent
- outcome, duration, OS, Python version and schema version
- for an early exit, one code from a fixed list, never the message
- a random run id (shared by one command's events) and a random install id

The session start check (`startup-check`) sends the same event.

A failure sends a second event with the exception type, up to three chained exception types, and the file, function, module and line of the llm-prompts, cline-hooks and mcp-memory frames, plus `github` or `mcp` when the failure came from that service. Only exceptions defined in llm-prompts and cline-hooks send their message, scrubbed of local values, paths, URLs, hosts, emails, IPs and long opaque strings and cut to 200 characters. Every other exception, including mcp-memory ones, sends its type and `<message withheld>`. A failed command sends only its exit status. Exits and Ctrl-C send no failure event.

Each llm-prompts command run with agents installed writes `telemetry.json` next to `config.toml`. It holds your opt-out choice, when you made it, and the install id. mcp-memory reads this file, so it follows the same opt-out and sends its events under the same install id. The file itself is never sent.

Never sent: paths, usernames, hostnames, repo names, names of overlays not installed from github.com, prompt or config contents.

[Public totals](https://eu.posthog.com/shared/qdUBSB6XFctcGy5jzZ4TCqeNN3UXcQ)
