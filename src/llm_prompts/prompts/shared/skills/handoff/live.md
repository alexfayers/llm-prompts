# Live handoff

- MUST start an agent of the same kind in a new pane of the current tab, and send the handoff doc as its prompt. The prompt MUST tell it to use `pickup` and to confirm its understanding of the asks to this session at the address below.
- In Claude Code:
  - MUST start the new session with `herdr agent start <new-name> --kind claude --pane <new-pane-id> -- --name <new-name>`, where `<new-pane-id>` is the new pane. Without `--name`, `ListAgents` shows it unnamed and `SendMessage` cannot reach it - the herdr name is only a pane label.
  - Address: this session's name from `ListAgents` (`<name>`) and this pane's ID (`<id>`) from `herdr pane current --current`. MUST send the handoff with `SendMessage`, not `herdr agent prompt`. The new session replies with `SendMessage` to `<name>`.
- Elsewhere: address is this pane's ID (`<id>`) from `herdr pane current --current`. The new session replies with `herdr agent prompt <id>`, or through a subagent when it has no shell.
- The prompt's FIRST LINE MUST be exactly `HANDOFF-ACK <id>` alone, above the doc's heading, naming this sending pane, never the new session. The `pickup` instruction follows it, then the doc.
- MUST confirm the new agent is running from `herdr agent get`, not from its own words.
- MUST NOT close the old session's pane until a reply containing `HANDOFF-ACK <id>` has arrived. Where the reply asks for more, MUST answer and wait for the next reply. Once a reply needs nothing more, MUST close only its own pane (`herdr pane close <id>`) as the last step, unless this session keeps running alongside the new one.
- On any failure, or if the reply never arrives, MUST keep the old pane open and report to the user. MUST NOT resend a stalled prompt.
