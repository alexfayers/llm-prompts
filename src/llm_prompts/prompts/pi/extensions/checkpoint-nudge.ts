// Appends a short checkpoint reminder to a tool result each time another threshold of tool-result tokens builds up since the last user message, until the model calls checkpoint.
// Env: CHECKPOINT_NUDGE_TOKENS (tool-result tokens per nudge, default 10000)
// Env: PI_HERDSMAN_MAILBOX (set for Herdsman delegates, which are never nudged)
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const DEFAULT_NUDGE_TOKENS = 10_000;

const textTokens = (content: { type: string; text?: string }[]) =>
	Math.ceil(content.reduce((sum, block) => sum + (block.type === "text" ? (block.text?.length ?? 0) : 0), 0) / 4);

export default function (pi: ExtensionAPI) {
	if (process.env.PI_HERDSMAN_MAILBOX) return;
	const threshold = Number(process.env.CHECKPOINT_NUDGE_TOKENS) || DEFAULT_NUDGE_TOKENS;
	let calls = 0;
	let tokens = 0;
	let nudgedAt = 0;
	const reset = () => void (calls = tokens = nudgedAt = 0);
	pi.on("agent_start", reset);
	pi.on("input", reset);
	pi.on("tool_result", (event) => {
		if (event.parentToolCallId) return;
		if (event.toolName === "checkpoint") return reset();
		calls++;
		tokens += textTokens(event.content);
		if (tokens - nudgedAt < threshold) return;
		nudgedAt = tokens;
		const text = `[checkpoint] ${calls} calls, ~${Math.round(tokens / 1000)}K tokens since the last user message. If a detour is finished, checkpoint rewind to the call before it, or to a mark set before it, with a summary before replying.`;
		return { content: [...event.content, { type: "text" as const, text }], structuredContent: event.structuredContent };
	});
}
