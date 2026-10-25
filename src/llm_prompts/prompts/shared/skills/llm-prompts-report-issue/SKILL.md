---
name: llm-prompts-report-issue
description: Report a bug in llm-prompts, cline-hooks, or mcp-memory as a GitHub issue. Use when a rule, skill, hook, memory tool or CLI misbehaves.
---

# Reporting an issue

Feature requests and ideas: `llm-prompts-request` skill.

## Target repo

- MUST pick the repo where the faulty behaviour lives:
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
- Body: a few short paragraphs. What happens literally, what was expected, how to reproduce if known.
- MUST carry exactly ONE ask. Several problems -> one issue each.
- MUST NOT paste secrets, tokens, private paths or other private info.

## Open

- MUST show the user the target repo, title and body, and ask the user for approval.
- MUST NOT run `gh issue create` before the user approves. Edits requested -> redraft, show again.
- On approval (github.com): `gh issue create -R <owner/name> --title "<title>" --body-file -`, adding `--label bug` only if the repo has it (`gh label list -R <owner/name>`).
- MUST report the issue URL.
- MUST NOT push, open a PR, or comment on other issues.
