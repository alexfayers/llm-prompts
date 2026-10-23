---
name: pi-help
description: Walk a new user through what is installed in pi and answer questions about it. Use when the user asks what is set up, how pi works here, or what a command, extension or agent does.
disable-model-invocation: true
---

# pi-help

Guided tour of this pi setup. Plain words.

## Discover

- MUST run `llm-prompts source pi` and read its `extensions:`, `agents:` and `seed:` lists before offering topics.
- MUST read line 1 and the following `//` header lines of each listed extension. MUST open the extension source before naming a config key, command or env var that the header does not give.
- MUST read `description` in `package.json` of each package in `settings.json` `packages`, under `npm/node_modules/<package>` in the pi agent dir or the source dir of a git or local package.
- MUST read the `description` frontmatter of each listed agent.
- MUST read the installed copy of each listed seed file, at the same relative path in the pi agent dir. MUST NOT report seed defaults as the user's settings, since a seed never overwrites an existing file.
- MUST build topics from what you found plus the facts below. MUST NOT list what is not installed.
- MUST name a command only after finding it in `/help`, a header or a source file.

## How to run

- MUST go one topic at a time: 2-4 short sentences, then ask what next.
- MUST NOT dump all topics. Offer the list. The user picks.
- MUST answer a question first, then offer to go on.

## Facts no file records

- MUST NOT state model names from memory. Agent names are `<kind>-<model>-<effort>`. MUST check `/agents` or the installed definitions.
- MUST describe your session as the lead that hands work to background agents.
- An agent definition MAY set `extensions: [a, b]` to load only those, plus `pi/agent-extensions.json` and extensions calling `registerProvider(`. Names: `builtin:x`, files or packages. `?` marks optional. Omitting `extensions` loads all extensions.
- MUST tell the user to run `/reload` after editing extensions, packages, settings, agents or `AGENTS.md`.
- `pi/agent-additions.json` `{agent: {key: [t]}}` adds `pi_skills`, `extensions`, variants to an agent.
- MUST NOT describe net-guard as a security boundary.
- MUST explain `promptMaxRows` and `promptFieldMaxWidth` of 1000000 as making the permission prompt start expanded.
- MUST explain `forwardingTimeoutMs` at its maximum as a permission ask that never times out.
- MUST explain `tools.sourceCheck.enabled` false in `web-search.json` as no `source_check` tool.
