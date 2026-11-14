// Adds the checkpoint tool: mark a point, then rewind to replace the work since a mark or an earlier tool call with a summary or the raw tool results.
// Env: CHECKPOINT_SHAPE (set to result to carry the fold in the rewind tool result instead of a separate message)
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Block = { type: string; id?: string; name?: string; text?: string; arguments?: unknown };
type Details = { action?: "mark" | "rewind"; name?: string; target?: string; mode?: "summary" | "raw"; summary?: string };
type Message = { role: string; content?: string | Block[]; toolCallId?: string; toolName?: string; isError?: boolean; details?: Details; customType?: string };
type Entry = { id: string; type: string; message?: Message };
type Projected = { sourceEntry: Entry; messages: Message[] };
type Mark = { name: string; resultEntryId: string; callId: string };
type Call = { name: string; callId: string; args: unknown };

const RECENT_CALLS = 5;

const text = (content: Message["content"]): string =>
	typeof content === "string" ? content : (content ?? []).map((block) => block.text ?? "").join("\n");

const callIds = (message?: Message): string[] =>
	(Array.isArray(message?.content) ? message.content : []).flatMap((block) => (block.type === "toolCall" && block.id ? [block.id] : []));

const isCheckpointResult = (message: Message | undefined, action: Details["action"]): boolean =>
	message?.role === "toolResult" && message.toolName === "checkpoint" && message.details?.action === action;

function visibleMarks(entries: Projected[]): Mark[] {
	return entries.flatMap(({ sourceEntry, messages }) =>
		isCheckpointResult(sourceEntry.message, "mark") && messages.length > 0
			? [{ name: sourceEntry.message?.details?.name ?? "", resultEntryId: sourceEntry.id, callId: sourceEntry.message?.toolCallId ?? "" }]
			: [],
	);
}

/** Visible non-checkpoint tool calls, newest first. */
function recentCalls(entries: Projected[]): Call[] {
	return entries
		.filter((entry) => entry.messages.length > 0 && entry.sourceEntry.message?.role === "assistant")
		.flatMap(({ sourceEntry }) => (Array.isArray(sourceEntry.message?.content) ? sourceEntry.message.content : []).filter((block) => block.type === "toolCall" && block.id && block.name !== "checkpoint"))
		.map((block) => ({ name: block.name ?? "", callId: block.id ?? "", args: block.arguments }))
		.reverse();
}

/** The call id a rewind target names: a mark, `-N` (the Nth call back) or `<tool>#<n>` (the nth call of that tool back). */
function resolve(entries: Projected[], target: string): string | undefined {
	const mark = visibleMarks(entries).find((candidate) => candidate.name === target);
	if (mark) return mark.callId;
	const calls = recentCalls(entries);
	const back = /^-([1-9]\d*)$/.exec(target);
	if (back) return calls[Number(back[1]) - 1]?.callId;
	const named = /^([^#]+)#([1-9]\d*)$/.exec(target);
	return named ? calls.filter((call) => call.name === named[1])[Number(named[2]) - 1]?.callId : undefined;
}

function boundary(entries: Projected[], callId: string): number {
	const ids = callIds(entries.find((entry) => callIds(entry.sourceEntry.message).includes(callId))?.sourceEntry.message);
	return entries.reduce((last, entry, index) => (ids.includes(entry.sourceEntry.message?.toolCallId ?? "") ? index : last), -1);
}

function rawResults(messages: Message[]): string {
	const calls = new Map<string, Block>();
	for (const message of messages)
		for (const block of Array.isArray(message.content) ? message.content : []) if (block.type === "toolCall" && block.id) calls.set(block.id, block);
	return messages
		.flatMap((message) => {
			if (message.customType === "checkpoint-fold" || isCheckpointResult(message, "rewind")) return [text(message.content)];
			if (message.role !== "toolResult" || message.toolName === "checkpoint") return [];
			return [`[${message.toolName} ${JSON.stringify(calls.get(message.toolCallId ?? "")?.arguments)}]\n${text(message.content)}`];
		})
		.join("\n\n");
}

export default function (pi: ExtensionAPI) {
	const inResult = process.env.CHECKPOINT_SHAPE === "result";

	pi.registerTool({
		name: "checkpoint",
		label: "Checkpoint",
		executionMode: "sequential",
		description:
			"mark: remember this point and return its id (call alone, optional name). rewind (call alone): fold everything after `target` (a mark, default: latest, or a tool call: `-N` for the Nth call back, `<tool>#<n>` for the nth call of that tool back) into `summary` (mode summary) or the raw tool results (mode raw). User messages stay. Later marks and earlier folds inside that region are removed too. The summary must cover them. Rewinds in place on the same branch, unlike /tree.",
		parameters: Type.Object({
			action: Type.Union([Type.Literal("mark"), Type.Literal("rewind")]),
			name: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9_.-]{1,40}$" })),
			target: Type.Optional(Type.String()),
			mode: Type.Optional(Type.Union([Type.Literal("summary"), Type.Literal("raw")])),
			summary: Type.Optional(Type.String()),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const entries = ctx.sessionManager.buildSessionProjection().entries as unknown as Projected[];
			const visible = visibleMarks(entries).map((mark) => mark.name);
			const reply = (message: string, details: Details) => ({ content: [{ type: "text" as const, text: message }], details });
			if (params.action === "mark") {
				let counter = (ctx.sessionManager.getBranch() as Entry[]).filter((entry) => isCheckpointResult(entry.message, "mark")).length + 1;
				while (!params.name && visible.includes(`m${counter}`)) counter += 1;
				const name = params.name ?? `m${counter}`;
				if (visible.includes(name)) throw new Error(`checkpoint "${name}" exists`);
				return reply(`checkpoint "${name}" marked (marks: ${[...visible, name].join(", ")})`, { action: "mark", name });
			}
			const target = params.target ?? visible.at(-1);
			if (!target || !resolve(entries, target)) {
				const calls = recentCalls(entries)
					.slice(0, RECENT_CALLS)
					.map((call, index) => `-${index + 1} ${call.name} ${JSON.stringify(call.args)}`);
				const marks = visible.length ? `a mark (${visible.join(", ")})` : "a mark (no marks yet, call mark first)";
				throw new Error(
					`${target ? `unknown checkpoint "${target}"` : "no marks to rewind to"}. Target ${marks}, -N for the Nth tool call back, or <tool>#<n> for the nth call of that tool back.${calls.length ? `\nRecent calls:\n${calls.join("\n")}` : ""}`,
				);
			}
			const mode = params.mode ?? "summary";
			if (mode === "summary" && !params.summary) throw new Error("rewind in summary mode needs a summary");
			return reply(`rewinding to "${target}"`, { action: "rewind", target, mode, summary: params.summary });
		},
	});

	pi.on("turn_end", (event, ctx) => {
		const results = event.toolResults as unknown as Message[];
		const index = results.findIndex((result) => isCheckpointResult(result, "rewind") && !result.isError);
		if (index < 0) return;
		const { target: targetName, mode, summary } = results[index].details ?? {};
		const entries = ctx.sessionManager.buildSessionProjection().entries as unknown as Projected[];
		const callId = targetName && resolve(entries, targetName);
		if (!callId) return;
		const start = boundary(entries, callId);
		const resultEntryId = entries.find((entry) => entry.sourceEntry.message?.toolCallId === results[index].toolCallId)?.sourceEntry.id;
		if (start < 0 || !resultEntryId) return;
		const region = entries
			.slice(start + 1)
			.filter((entry) => entry.messages.length > 0 && (entry.sourceEntry.type === "message" || entry.sourceEntry.type === "custom_message"))
			.filter((entry) => entry.sourceEntry.type === "custom_message" || entry.sourceEntry.message?.role === "assistant" || entry.sourceEntry.message?.role === "toolResult");
		const regionIds = region.map((entry) => entry.sourceEntry.id);
		const removed = visibleMarks(entries).filter((mark) => regionIds.includes(mark.resultEntryId)).map((mark) => mark.name);
		const turnIds = [event.messageEntryId, ...event.toolResultEntryIds];
		const content = mode === "raw" ? rawResults(region.filter((entry) => !(inResult ? turnIds : [resultEntryId]).includes(entry.sourceEntry.id)).flatMap((entry) => entry.messages)) : (summary ?? "");
		const removedMarks = removed.length ? `\n\nMarks removed with them: ${removed.join(", ")}.` : "";
		const foldText = `[checkpoint ${mode} to "${targetName}"] The steps since ${visibleMarks(entries).some((mark) => mark.name === targetName) ? "mark" : "call"} "${targetName}" were run, then removed from your context. Their outcome:\n${content}${removedMarks}`;
		const kept = inResult ? turnIds : [];
		const edit = (targetId: string, replacement: { content: { type: "text"; text: string }[] } | null) => ({ type: "context_edit" as const, targetId, replacement });
		return {
			entries: [
				...event.entries,
				...regionIds.filter((id) => !kept.includes(id)).map((id) => edit(id, null)),
				inResult
					? edit(resultEntryId, { content: [{ type: "text", text: foldText }] })
					: { type: "custom_message" as const, customType: "checkpoint-fold", content: foldText, display: true },
			],
		};
	});
}
