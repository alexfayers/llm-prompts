---
name: llm-prompts-request
description: Request a feature in llm-prompts, cline-hooks, or mcp-memory as a GitHub issue. Use when the user wants a rule, skill, hook, memory tool or CLI changed.
---

# Requesting a feature

Bugs and annoyances: `llm-prompts-report-issue` skill.

## Target repo

- MUST pick the repo that would own the change:
  - `llm-prompts` - rules, skills, workflows, agents, installer, `llm-prompts` CLI.
  - `cline-hooks` - hook plugins, hook-emitted blocks and notes.
  - `mcp-memory` - memory server, memory tools, memory CLI.
- MUST get the repo's GitHub `owner/name` from its checkout, never guess it: `llm-prompts source <agent>` gives the path, then `git -C <path> remote get-url origin`.
- Another overlay's repo is in scope. Its source is the `source` of its `[[tools]]` entry in `~/.config/llm-prompts/config.toml`.
- MUST detect the remote host from that source (or `git remote get-url origin` of its checkout), never from its name.
- Host is not github.com -> MUST NOT use `gh`. File with that host's own issue tooling only if its docs or `--help` confirm how. Otherwise MUST ask the user how to file there.
- On github.com, MUST search first: `gh issue list -R <owner/name> --search "<keywords>" --state all`. A match -> point the user at it, MUST NOT file a duplicate.

## Draft

- Title: short, plain, no `type:` prefix.
- Body: a few short paragraphs. Open with the need, then the proposal as a hedged question. Cover the current behaviour only where it explains the need.
- MUST carry exactly ONE ask. Several ideas -> one issue each.
- MUST NOT paste secrets, tokens, private paths or other private info.

## Open

- MUST show the user the target repo, title and body, and ask the user for approval.
- MUST NOT run `gh issue create` before the user approves. Edits requested -> redraft, show again.
- On approval (github.com): `gh issue create -R <owner/name> --title "<title>" --body-file -`, adding `--label enhancement` only if the repo has it (`gh label list -R <owner/name>`).
- MUST report the issue URL.
- MUST NOT push, open a PR, or comment on other issues.
