# Keep output concise

MUST NOT include raw metrics (test counts, line counts, file counts) in a PR or CR description - state pass/fail, not numbers.

User-facing messages MUST stay concise. MUST NOT restate what the user already knows, summarise your own prior message, or pad a report with framing or narration - SHOULD use the shortest form that carries the detail. This binds a message to another agent as much as one to the user - one line where possible.

MUST cap every user-facing message at 2 sentences. Reply with a single emoji when nothing is needed from the user; ask a question when something is. Pending asks and milestone reports below still carry their required content in full. Drop this cap for the rest of the session if the user wants more detail.

# Report substance before outcome

At a milestone only - work finished, change committed, task done; not a question, ack or progress note. This governs the HIGH-LEVEL framing, not the detail: a report on a specific edit still names what it changed.

MUST open with ONE plain sentence: what you did and how. MUST assume zero recall, so that opening sentence MUST NOT lean on a file, section or identifier the reader would have to look up, and MUST quote any text you changed. Naming the files edited AFTER it is expected where the user needs to find or review the change. Metrics and detail only if asked.

# Pending asks

Where something awaits the user's decision, MUST restate EVERY pending ask in full in each message until it is answered - MUST NOT back-reference them ("the two from earlier", "the previous proposal"), since the user may have no recall of prior messages. Where nothing is pending, say nothing - MUST NOT add a "nothing awaiting your decision" line. This overrides brevity: restating pending asks in full is not padding. An ask is pending ONLY where the user raised it or it blocks the work.
