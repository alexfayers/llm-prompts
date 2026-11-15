// Caps long tool results to a head and tail and adds the result_fetch tool to read the full text back.
// Env: RESULT_CAP_CHARS (longest result kept whole, default 6000)
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const DEFAULT_CAP = 6000;
const HEAD_SHARE = 2 / 3;
const EXEMPT = new Set(["read", "edit", "write", "result_fetch", "checkpoint", "ask_user", "asks"]);
const HANDOFF_LINE = /^(ASK:|DENIED:)/m;

const capChars = (): number => Number(process.env.RESULT_CAP_CHARS) || DEFAULT_CAP;

export function shape(full: string, ref: string, cap: number): string {
	const head = Math.floor(cap * HEAD_SHARE);
	const marker = `[capped: ${full.length} chars, ref ${ref}; result_fetch({ref, offset?, limit?, pattern?})]`;
	return `${full.slice(0, head)}\n${marker}\n${full.slice(full.length - (cap - head))}`;
}

type Stored = { type: string; customType?: string; data?: { ref: string; text: string } };

const reply = (text: string, isError = false) => ({ content: [{ type: "text" as const, text }], details: undefined, isError });

function select(full: string, pattern: string | undefined): string {
	if (!pattern) return full;
	const regex = new RegExp(pattern);
	return full
		.split("\n")
		.flatMap((line, index) => (regex.test(line) ? [`${index}: ${line}`] : []))
		.join("\n");
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "result_fetch",
		label: "Result fetch",
		description:
			"Read the full text of a capped tool result by its `ref`. `pattern` (regex) keeps only matching lines, as `<line>: <text>`. `offset` and `limit` slice the text in characters.",
		parameters: Type.Object({
			ref: Type.String(),
			offset: Type.Optional(Type.Integer({ minimum: 0 })),
			limit: Type.Optional(Type.Integer({ minimum: 1 })),
			pattern: Type.Optional(Type.String()),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const stored = (ctx.sessionManager.getBranch() as Stored[]).find((entry) => entry.customType === "result-cap" && entry.data?.ref === params.ref);
			if (!stored?.data) return reply(`Unknown ref ${params.ref}`, true);
			let selected: string;
			try {
				selected = select(stored.data.text, params.pattern);
			} catch {
				return reply(`Invalid pattern ${params.pattern}`, true);
			}
			const offset = params.offset ?? 0;
			const end = offset + (params.limit ?? capChars());
			return reply(selected.slice(offset, end) + (end < selected.length ? `\n[more: offset ${end}]` : ""));
		},
	});

	pi.on("tool_result", (event) => {
		if (event.parentToolCallId || event.isError || EXEMPT.has(event.toolName) || event.content.some((block) => block.type !== "text")) return;
		const full = event.content.map((block) => (block.type === "text" ? block.text : "")).join("\n");
		if (full.length <= capChars() || HANDOFF_LINE.test(full)) return;
		const ref = `rc-${event.toolCallId}`;
		try {
			pi.appendEntry("result-cap", { ref, text: full });
		} catch {
			return;
		}
		return { content: [{ type: "text" as const, text: shape(full, ref, capChars()) }] };
	});
}
