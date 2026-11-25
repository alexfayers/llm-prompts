// Adds the checkpoint tool: mark a point, then rewind to replace the work since a mark or an earlier tool call with a summary or the raw tool results.
// Also appends a short checkpoint reminder to a tool result each time another threshold of tool-result tokens builds up since the last user message, until the model calls checkpoint. Only the first reminder after a reset carries the advice.
// Once per run it also names the mark or tool call to rewind to, when the run's tokens cost more to carry than a rewind costs.
// Config: settings.json llmPrompts.checkpoint.shape (set to "result" to carry the fold in the rewind tool result instead of a separate message)
// Config: settings.json llmPrompts.checkpoint.nudgeTokens (tool-result tokens per nudge, default 10000)
// Env: PI_CONTEXT_CHILD (set for delegates, which are never nudged), PI_CACHE_RETENTION (long prices cache writes at the one hour rate)
import { calculateCost, type Api, type Model, type Usage } from "@earendil-works/pi-ai";
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
const KEEP_USING_CHECKPOINTS = "Keep using checkpoints: mark before a detour, rewind after it.";

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

export const DEFAULT_NUDGE_TOKENS = 10_000;

const textTokens = (content: { type: string; text?: string }[]) =>
	Math.ceil(content.reduce((sum, block) => sum + (block.type === "text" ? (block.text?.length ?? 0) : 0), 0) / 4);

type Settings = { shape?: string; nudgeTokens?: number };
const readSettings = (pi: ExtensionAPI): Settings | undefined => (pi.getSettings() as { llmPrompts?: { checkpoint?: Settings } }).llmPrompts?.checkpoint;

/**
 * Cost invariant, at the active model's effective prices: a rewind pays once the run's tokens beyond the summary, read from cache by each expected later request,
 * outweigh writing and generating the summary: `(tokens - SUMMARY_TOKENS) * EXPECTED_REMAINING_REQUESTS * cacheRead > SUMMARY_TOKENS * (cacheWrite + output)`.
 */
export const EXPECTED_REMAINING_REQUESTS = 20;
export const SUMMARY_TOKENS = 1_000;
export const MIN_RUN_CALLS = 5;

const price = (model: Model<Api>, usage: Partial<Usage>) =>
	calculateCost(model, { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, ...usage, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }).total;

/** Bedrock models that pi gives cache points, as its own `supportsPromptCaching` decides: Claude 3.5 Haiku, 3.7 Sonnet, 4.x and 5. */
const BEDROCK_CACHE_POINT_MODEL = /fable-5|opus-5|sonnet-5|haiku-5|-4-|claude-3-7-sonnet|claude-3-5-haiku/;

/** Whether pi asks this model for one hour cache writes under long retention: always on Anthropic unless its compat turns it off, and on Bedrock only for the models that get cache points. */
function requestsOneHourWrites(model: Model<Api>, longRetention: boolean): boolean {
	if (!longRetention) return false;
	if (model.api === "anthropic-messages") return (model.compat as { supportsLongCacheRetention?: boolean } | undefined)?.supportsLongCacheRetention !== false;
	const names = [model.id, model.name].map((name) => name?.toLowerCase().replace(/[\s_.:]+/g, "-") ?? "");
	return model.api === "bedrock-converse-stream" && names.some((name) => name.includes("claude")) && names.some((name) => BEDROCK_CACHE_POINT_MODEL.test(name));
}

/** The usage of the summary request, classified as pi does: a model that prices cache writes writes them, and any other model bills the fresh tokens as input. */
function summaryUsage(model: Model<Api>, longRetention: boolean): Partial<Usage> {
	if (!(model.cost.cacheWrite > 0)) return { input: SUMMARY_TOKENS, output: SUMMARY_TOKENS };
	return { cacheWrite: SUMMARY_TOKENS, cacheWrite1h: requestsOneHourWrites(model, longRetention) ? SUMMARY_TOKENS : 0, output: SUMMARY_TOKENS };
}

/** Prices through pi's `calculateCost`, so the context-size tier and the one hour cache-write rate apply. */
function rewindPays(model: Model<Api>, runTokens: number, contextTokens: number, longRetention: boolean): boolean {
	const context = Math.max(contextTokens, runTokens);
	const carried = Math.max(runTokens - SUMMARY_TOKENS, 0);
	const carryCost = EXPECTED_REMAINING_REQUESTS * (price(model, { cacheRead: context }) - price(model, { cacheRead: context - carried }));
	const rest = { cacheRead: context - runTokens };
	return carryCost > price(model, { ...rest, ...summaryUsage(model, longRetention) }) - price(model, rest);
}

/** The rewind target for the run, found by call id: the mark that opened it, else the call before its first call, else that first call. Results of the target's own batch stay, so they are not counted as removed. */
function rewindPlan(entries: Projected[], markName: string | undefined, results: Map<string, number>) {
	const calls = recentCalls(entries);
	const first = [...calls].reverse().find((call) => results.has(call.callId));
	const mark = markName ? visibleMarks(entries).find((candidate) => candidate.name === markName) : undefined;
	const before = first && (calls[calls.indexOf(first) + 1] ?? first);
	const anchor = mark ? { target: mark.name, callId: mark.callId } : before && { target: `-${calls.indexOf(before) + 1}`, callId: before.callId };
	if (!anchor) return;
	const kept = callIds(entries.find((entry) => callIds(entry.sourceEntry.message).includes(anchor.callId))?.sourceEntry.message);
	const removed = [...results].filter(([id]) => !kept.includes(id)).map(([, tokens]) => tokens);
	return { target: anchor.target, calls: removed.length, tokens: removed.reduce((sum, tokens) => sum + tokens, 0) };
}

function nudge(pi: ExtensionAPI) {
	let calls = 0;
	let tokens = 0;
	let nudgedAt = 0;
	let markName: string | undefined;
	let suggested = false;
	let results = new Map<string, number>();
	const reset = () => void ((calls = tokens = nudgedAt = 0), (markName = undefined), (suggested = false), (results = new Map()));
	pi.on("agent_start", reset);
	pi.on("input", reset);
	pi.on("tool_result", (event, ctx) => {
		if (event.parentToolCallId) return;
		if (event.toolName === "checkpoint") {
			reset();
			return void (markName = (event.details as Details | undefined)?.action === "mark" ? (event.details as Details).name : undefined);
		}
		calls++;
		const resultTokens = textTokens(event.content);
		tokens += resultTokens;
		results.set(event.toolCallId, resultTokens);
		const lines: string[] = [];
		if (tokens - nudgedAt >= (readSettings(pi)?.nudgeTokens || DEFAULT_NUDGE_TOKENS)) {
			const advice = nudgedAt === 0 ? " If a detour is finished, checkpoint rewind to the call before it, or to a mark set before it, with a summary before replying." : "";
			nudgedAt = tokens;
			lines.push(`[checkpoint] ${calls} calls, ~${Math.round(tokens / 1000)}K tokens since the last user message.${advice}`);
		}
		const model = ctx.model as Model<Api> | undefined;
		const plan = !suggested && model && calls >= MIN_RUN_CALLS ? rewindPlan(ctx.sessionManager.buildSessionProjection().entries as unknown as Projected[], markName, results) : undefined;
		if (model && plan && plan.calls >= MIN_RUN_CALLS && rewindPays(model, plan.tokens, ctx.getContextUsage?.()?.tokens ?? 0, process.env.PI_CACHE_RETENTION === "long")) {
			suggested = true;
			lines.push(`[checkpoint] rewind to ${JSON.stringify(plan.target)}: ${plan.calls} calls, ~${Math.round(plan.tokens / 1000)}K tokens that every later request would carry. checkpoint rewind with a summary costs less.`);
		}
		if (lines.length) return { content: [...event.content, ...lines.map((text) => ({ type: "text" as const, text }))], structuredContent: event.structuredContent };
	});
}

export default function (pi: ExtensionAPI) {
	if (!process.env.PI_CONTEXT_CHILD) nudge(pi);

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
		const inResult = readSettings(pi)?.shape === "result";
		const content = mode === "raw" ? rawResults(region.filter((entry) => !(inResult ? turnIds : [resultEntryId]).includes(entry.sourceEntry.id)).flatMap((entry) => entry.messages)) : (summary ?? "");
		const removedMarks = removed.length ? `\n\nMarks removed with them: ${removed.join(", ")}.` : "";
		const foldText = `[checkpoint ${mode} to "${targetName}"] The steps since ${visibleMarks(entries).some((mark) => mark.name === targetName) ? "mark" : "call"} "${targetName}" were run, then removed from your context. Their outcome:\n${content}${removedMarks}\n\n${KEEP_USING_CHECKPOINTS}`;
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
