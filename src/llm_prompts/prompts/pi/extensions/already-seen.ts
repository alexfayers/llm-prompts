// Replaces a repeated read-only tool result that is still visible in context with a short receipt.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TOOLS = ["read", "grep", "find", "ls"];

type Block = { type: string; text?: string; id?: string; arguments?: unknown };
type Message = { role: string; content?: string | Block[]; toolCallId?: string; toolName?: string };
type Projected = { sourceEntry: { id: string }; messages: Message[] };

const blocks = (message: Message): Block[] => (Array.isArray(message.content) ? message.content : []);
const textOf = (content: Block[]) => content.map((block) => block.text ?? "").join("");

const RECEIPT = /^unchanged since entry (\S+), still in context above\. If that entry is gone, run the call again$/;

export const receipt = (entryId: string): string => `unchanged since entry ${entryId}, still in context above. If that entry is gone, run the call again`;

/** Returns the id of the entry a receipt points at. */
export const receiptEntryId = (text: string): string | undefined => RECEIPT.exec(text)?.[1];

/** Returns the id of the visible entry that holds an earlier result of the same call with identical text. */
export function findVisibleDuplicate(entries: Projected[], toolName: string, input: unknown, text: string): string | undefined {
	const calls = new Map<string, string>();
	for (const message of entries.flatMap((entry) => entry.messages))
		for (const block of message.role === "assistant" ? blocks(message) : []) if (block.type === "toolCall" && block.id) calls.set(block.id, JSON.stringify(block.arguments));
	return entries.find((entry) =>
		entry.messages.some((message) => message.role === "toolResult" && message.toolName === toolName && calls.get(message.toolCallId ?? "") === JSON.stringify(input) && textOf(blocks(message)) === text),
	)?.sourceEntry.id;
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_result", (event, ctx) => {
		const content = event.content as Block[];
		if (!TOOLS.includes(event.toolName) || event.isError || event.parentToolCallId || content.some((block) => block.type !== "text")) return;
		const entryId = findVisibleDuplicate(ctx.sessionManager.buildSessionProjection().entries as unknown as Projected[], event.toolName, event.input, textOf(content));
		return entryId ? { content: [{ type: "text" as const, text: receipt(entryId) }] } : undefined;
	});
}
