# Hooks - Kiro-specific

A PreToolUse hook can block a tool call (exit code 2); Kiro CLI surfaces this as "PreToolHook blocked the tool execution: <message>" fed back to you, distinct from an actual user-initiated cancellation. Never attribute a blocked call to the user cancelling it - the message is already visible to you, so read it and act on it rather than assuming the user stopped it.

A bare, contentless "cancelled by the user" result on one call in a parallel batch, alongside a sibling call in the same batch that shows real hook block text, does not mean the user cancelled anything. Root cause is unconfirmed and not tied to call position or tool type - retry the affected call alone, outside a batch, to see its real outcome before drawing any conclusion from the bare result.
