# Benchmark

`llm-prompts benchmark` runs real claude and pi agents through scenarios on two llm-prompts refs and reports whether task success, peak context or cost got better or worse.

```bash
llm-prompts benchmark --level light
```

Run it from an llm-prompts checkout. Any commit, branch or `:worktree` works for either ref. Every run has its own memory server and config, so your live memory, config and installs are never touched.

## Options

| Option | Meaning |
|---|---|
| `--a REF`, `--b REF` | Refs to compare (default: `origin/main` and `:worktree`). |
| `--a-tool NAME=SOURCE`, `--b-tool NAME=SOURCE` | Use this source for a configured tool (such as `mcp-memory`) in that ref only. Repeatable. A remote source must end in `@<40 character commit sha>`, or that side's runs are not reused. |
| `--b-env NAME=VALUE` | Set this environment variable for the agents of ref B only. Repeatable. |
| `--no-reuse` | Run A and B again instead of reusing finished runs. |
| `--level LEVEL` | `light`, `medium` or `heavy` (default: `light`). A level includes all lower levels. |
| `--agents LIST` | Comma separated agents (default: `claude,pi`). |
| `--model AGENT=ID` | Model id for one agent. Repeatable. |
| `--repeats N` | Run every scenario exactly N times per agent and ref. Without it, each runs once and then repeats, see [Repeats](#repeats). |
| `--max-repeats N` | Without `--repeats`, the most runs per scenario, agent and ref (default: 3). |
| `--overlays`, `--no-overlays` | Use the configured overlays or not (default: on). |
| `-j N`, `--jobs N` | Parallel runs (default: `jobs` under `[benchmark]` in `config.toml`, else 4). |
| `--scenario ID` | Run only this scenario. Repeatable. |
| `--fail-fast` | Stop early on a setup error, and skip the rest of a scenario once its repeats keep failing the same check. |
| `--fail-fast-after N` | With `--fail-fast`, how many repeats must fail the same check (default: 3). |
| `--estimate` | Print the token estimate and exit. |
| `--pr URL\|N` | Show the `## Benchmark` section for this pull request of the current repository. |
| `--run RUN_ID` | With `--pr`, use this finished run instead of running again. |
| `--apply` | With `--pr`, write the section into the pull request body. |
| `--no-os-sandbox` | Run without the OS sandbox. |
| `--judge HARNESS` | `auto`, `pi` or `claude` (default: `auto`: pi when on PATH, else claude). |

```toml
# ~/.config/llm-prompts/config.toml
[benchmark]
jobs = 6
```

Runs need `sandbox-exec` (macOS) or `bwrap` (Linux) unless `--no-os-sandbox` is given.

## Exit codes

- `0`: no regression.
- `1`: a regression.
- `2`: the run stopped.

## Output

The end of a run shows a table comparing A and B per scenario and agent: pass rate, start->peak context, cost, time, model turns and failed test runs. The last two lines are the paths of the reports.

The run folder under `~/.local/state/llm-prompts/benchmark/runs/` holds:

- `results.jsonl`: one row per run.
- `report.md` and `report.json`: the comparison, with the gate result and the actual token use.
- `pr.md`: the pull request section.
- One folder per run, with its agent log, trace, memory and workspace.

Peak context is the largest prompt sent on one model call. Cost is the agent's own reported USD cost. Failed test runs count bash calls that ran `pytest` and were rejected or reported a failure.

Runs of A and of B are reused from earlier runs on the same side when nothing that shapes them changed. That includes the pinned build and, for B, `--b-env`. A reused run keeps its agent run and its checks run again against the current scenario.

A run that fails at startup on a throttling or credential error, before any model output or tool call, is retried. If it still fails, it is a startup error: it is left out of the pass rate and the gate.

## Repeats

Without `--repeats`, every scenario and agent runs once on each side. It runs again, on both sides, while the runs so far show a difference, up to `--max-repeats`:

- A and B have different pass rates.
- The context, cost or time rise is over its limit in the `[gate]`.
- A side has no counted run, because every run was a startup error.

A scenario with a follow-up repeats as a whole chain. Reused runs count as runs. A repeat is also reused when an earlier run has it. Each round waits for the previous one, and the runs of a round share the `-j` slots. With `--fail-fast`, a setup error stops the next rounds, and runs are not skipped for repeated failures of one check. The `--estimate` line shows the cost of one run per side and the most.

## Gate rules

A scenario regresses when:

- its pass rate drops by `max_pass_drop` or more and the 95% Wilson intervals of the A and B pass rates do not overlap, or
- its median peak context rises by more than `max_context_rise`.

A chain regresses when the median over repeats of its summed cost or wall time rises by more than `max_cost_rise` or `max_time_rise`. A chain is a base and its follow-ups down to one last follow-up. A scenario without follow-ups is a chain of one. The cost and time gates are those of the chain's last scenario.

Defaults are 0.34, 0.25, 0.5 and 0.5. A scenario can set its own under `[gate]`.

The context rule needs at least 3 completed runs on each side. The cost and time rules need at least 3 repeats on each side that finished every session. With fewer, a rise over its limit shows as a `Gate info:` line and does not breach the gate.

The `Overall` line summarises the run. The result is `improved` when B has more passing cells and no scenario's pass rate fell, `regressed` when B has fewer passing cells or the gate regressed, and `no change` otherwise. A scenario with `headline = true` is shown first.

## Attaching results to a pull request

```
llm-prompts benchmark --level medium --pr 354
llm-prompts benchmark --run <run id> --pr 354 --apply
```

`--pr` shows the `## Benchmark` section. `--apply` writes it into the pull request body, replacing an earlier one. The public report leaves out the run id, judge reasons and error text. If the section holds local paths, URLs, email addresses, IP addresses or ARNs, nothing is written and the exit code is 2.

## Add a scenario

Add one file named `<id>.toml` in `src/llm_prompts/benchmark/scenarios/`, with its workspace folder in `fixtures/`.

```toml
id = "recall-retry-policy"
level = "light"
agents = ["claude", "pi"]
workspace = "tiny-py"
project = "demo"
prompt = "Add retries to fetch() in fetch.py."
timeout_s = 300

[gate]
max_pass_drop = 0.34
max_context_rise = 0.25
max_cost_rise = 0.5
max_time_rise = 0.5

[[memory]]
name = "knowledge/demo-retry-policy"
entityType = "knowledge"
observations = ["Retries in the demo project use exponential backoff 2^n seconds, max 3 retries."]
relations = [{ target = "project/demo", type = "part-of" }]

[[check]]
kind = "memory_recalled"
entities = ["knowledge/demo-retry-policy"]
before = "Edit|Write"

[[check]]
kind = "not_called"
name = "Bash"
args_regex = "git\\s+push"

[[check]]
kind = "file_regex"
path = "fetch.py"
regex = "2\\s*\\*\\*"

[[check]]
kind = "judge"
path = "fetch.py"
rubric = "The retries use exponential backoff."
```

`setup` is a list of shell scripts run in the workspace right after its first commit. `delegation = true` (claude only) leaves the claude subagent tools on, and the `tool_called` and `not_called` checks take `by = "lead"` or `by = "subagent"`.

### Check kinds

| Kind | Arguments | Passes when |
|---|---|---|
| `tool_called` | `name`, `args_regex`, `before`, `before_args_regex`, `by` | A tool call matches, before any `before` call. |
| `not_called` | `name`, `args_regex`, `text_regex`, `by` | No tool call matches. |
| `tests_passed` | none | The last `pytest` bash call was not rejected and printed no failure. |
| `max_time` | `seconds` | The run took no longer than `seconds`. |
| `file_regex` | `path`, `regex` | The file matches the regex. |
| `memory_recalled` | `entities`, `before` | Every entity is in the start-up memory context, or a memory read was called. |
| `memory_written` | `name_regex`, `entity_type`, `relation`, `target_regex`, `regex`, `min_entities` | Enough matching entities have a new matching observation. |
| `memory_absent` | `name_regex`, `regex`, `include_existing` | No matching entity has a new matching observation. |
| `git_state` | `branch`, `since`, `commits`, `message_regex`, `remote` | The workspace repo matches. A `remote` must still have `branch` at `since`. |
| `command_exit` | `command`, `exit` (default 0) | The command exits with `exit`, run in the OS sandbox. |
| `files_unchanged` | `path` (one or a list) | The paths still match the first commit. |
| `files_changed` | `path` | Any path differs from the first commit. |
| `byte_size` | `path`, `max_growth_pct` (default 0) | The file is at most `max_growth_pct` percent larger than in the first commit. |
| `judge` | `rubric`, `path`, `name`, `args_regex`, `memory`, `failed`, `model` | A minimal judge answers PASS. |

### Judge

`judge` asks a minimal pi call (or claude when pi is not on PATH) to answer PASS or FAIL on the first line and give its reason after. It sees the rubric and the evidence, each part cut to 2,000 characters: the files in `path` (each edited file preceded by its first-commit original), the args of tool calls matching `name` and `args_regex`, the new memory observations when `memory = true`, the rejected tool calls when `failed = true`, or the final text when none is given. The model is `model` when set, else the agent's default judge model.

The judge's full reply is the check's `detail` in `results.jsonl` and in `judge-<n>.txt` in the run's folder. `report.md` lists every failed judge check under `## Judge reasons`.

### Follow-ups

A scenario with `base = "<id>"` is a follow-up. It gives only `id`, `level`, `prompt`, its checks, and optionally `timeout_s` and `gate`. It takes `workspace`, `project`, `memory`, `setup` and `agents` from its base. Selecting a follow-up also runs its base.

A follow-up runs as a fork of its base's agent session, so it reuses the base's cached prompt and reports only its own cost, time and turns. A base that errors gives its follow-ups the error `base failed: <error>`.

A follow-up with `fresh = true` starts a new session on the files and memory its base left. Only a fresh follow-up can follow another follow-up.

`report.md` has a `## Chains` table with the summed cost and time of each chain of two or more scenarios.
