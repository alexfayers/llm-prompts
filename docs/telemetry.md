# Telemetry

Every command sends one anonymous event to PostHog (EU). llm-prompts sends, writes and prints nothing while no agents are installed or when run with `--root`. The first run with an agent installed sends nothing and prints a notice. Turn it off with `DO_NOT_TRACK=1`, `LLM_PROMPTS_NO_TELEMETRY=1`, `CI`, or `enabled = false` under `[telemetry]` in `config.toml`. `LLM_PROMPTS_TELEMETRY_DEBUG=1` prints each event and sends it before the command exits.

Each event has:

- the command and the sorted names of its flags (never their values)
- agent names, overlay count, and the version of each overlay installed from a github.com source
- tool versions before and after: the installed `commit` of a remote source, `base` (the newest `origin/main` commit the install contains), `release` (the newest stable `vX.Y.Z` tag a local checkout contains, or a remote source's installed package version with a `v` prefix), and for local checkouts `local`, `dirty` and `ahead`. A local commit not on `origin/main` is never sent
- outcome, duration, OS, Python version and schema version
- for an early exit, one code from a fixed list, never the message
- for an update that stops with outcome `source_sync_failed`, the cause of the first failed source: `source_fetch_failed` (fetch failed), `source_release_failed` (could not move to the release), `source_cleanup_failed` (could not drop empty copies of merged commits) or `source_merge_failed` (could not fast-forward or rebase onto upstream)
- a random run id (shared by one command's events) and a random install id

The session start check (`startup-check`) sends the same event, plus `auto_update`: `started`, or why the automatic update did not start (`off`, `failed`, `session`, `local-changes`, `no-update`, `check-failed` when a source's update check failed, `lock-busy` when another check held the check lock, or `error` when the check or starting the update crashed). With `check-failed` it also sends `check_failed_source`: the first failed source: `llm-prompts`, `cline-hooks`, `mcp-memory`, `overlay` or `plugin`. When the background update finds a blocker after it takes the update lock, it sends an `update --auto` event with outcome `blocked` and that `auto_update` kind. When another update holds the lock, it sends outcome `stopped` with exit reason `update_running`.

A failure sends a second event with the exception type, up to three chained exception types, and the file, function, module and line of the llm-prompts, cline-hooks and mcp-memory frames, plus `github` or `mcp` when the failure came from that service. It also has `versions`: the release and commit of llm-prompts, cline-hooks and mcp-memory, in the same shape as the command's `to`. Only exceptions defined in llm-prompts and cline-hooks send their message, scrubbed of local values, paths, URLs, hosts, emails, IPs and long opaque strings and cut to 200 characters. Every other exception, including mcp-memory ones, sends its type and `<message withheld>`. A failed command sends only its exit status. Exits and Ctrl-C send no failure event.

Each pi session, lead or fork, sends one `pi_session` event when it ends, if it made a model call. It follows the same opt-out and install id, and sends nothing unless an llm-prompts command recorded the opt-out choice in the last 24 hours. It has:

- `role`: `main`, `reader`, `writer` or `other`, and `model_tier`: `opus`, `sonnet`, `haiku` or `other`, from the last model used
- `calls`, `cost`, `cost_per_call`, `context_avg` and `context_peak` (tokens per model call), `cache_read_share` (cache-read tokens over all input tokens), `compactions` and `wall_s`
- `inference_s` (time from each model request to its reply), `command_wait_s` (time while any tool call runs, outside `ask_user` and UI prompts) and `user_wait_s` (time in `ask_user`, UI prompts such as permission prompts, and idle time that ends with typed or RPC input), each with a `_share` of `wall_s`. The rest of `wall_s` is other time, such as waiting for a fork or a background process
- `llm_prompts`, `cline_hooks` and `mcp_memory`: the version entry of each tool, as in a command's `to`
- OS, Python version and schema version

A `pr_opened` event is sent when `llm-prompts contribute` opens a PR, or when a pi session's `gh pr create` bash call returns a PR URL. It has `role`, `model_tier` (from `PI_MODEL`), `time_to_pr_s` (seconds since the pi session started, or none outside pi), the tool versions and the platform fields.

A `pr_review` event is sent when an `llm-prompts pr` review loop ends. It has `rounds` (fix rounds), `end` (`clean` or `escalated`), `deferred` (the findings the last review deferred), the tool versions and the platform fields.

Neither event carries a PR number, repo, branch, title, path or any review text.

A fork's event carries its role and model tier, so fork count, runtime and cost by role and tier are counts and sums over fork events.

Each llm-prompts command run with agents installed and without `--root` writes `telemetry.json` next to `config.toml`. It holds your opt-out choice, when you made it, and the install id. mcp-memory reads this file, so it follows the same opt-out and sends its events under the same install id. The file itself is never sent.

Never sent: paths, usernames, hostnames, repo names, names of overlays not installed from github.com, prompt or config contents.

[Public totals](https://eu.posthog.com/shared/qdUBSB6XFctcGy5jzZ4TCqeNN3UXcQ)
