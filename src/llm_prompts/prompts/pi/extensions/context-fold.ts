// Folds old tool results and aborted turns into short stubs at the end of a run, keeping their full text fetchable with result_fetch.
// Env: CONTEXT_FOLD (on, dry to only record what it would fold, or off; default on), CONTEXT_FOLD_PENDING_TOKENS (tokens a fold must save, default 30000), CONTEXT_FOLD_KEEP_TOKENS (newest tokens never folded, default 40000)
import type { ContextEditableContent, ExtensionAPI, SessionBoundaryDraft } from "@earendil-works/pi-coding-agent";
import { receiptEntryId } from "./already-seen.ts";
import { HANDOFF_LINE } from "./result-cap.ts";

type Block = { type: string; id?: string; name?: string; text?: string; thinking?: string; arguments?: unknown };
type Message = { role: string; stopReason?: string; content?: string | Block[]; toolCallId?: string; toolName?: string; isError?: boolean };
type Entry = { id: string; type: string; message?: Message; customType?: string; data?: { ref: string; text: string } };
type Projected = { sourceEntry: Entry; messages: Message[] };
export type FoldPlan = { drafts: SessionBoundaryDraft[]; targets: string[]; savedTokens: number; argChars: number };

const DEFAULT_MODE = "on";
const DEFAULT_PENDING_TOKENS = 30000;
const DEFAULT_KEEP_TOKENS = 40000;
const CHARS_PER_TOKEN = 4;
const NEVER_FOLDED = new Set(["checkpoint", "asks", "ask_user", "compact_now", "fork", "reload_now"]);
const MIN_RESULT_CHARS = 800;
const ARGS_CHARS = 120;
const ABORTED_ARGS_CHARS = 60;
const ABORTED_TEXT_CHARS = 120;
const ERROR_CHARS = 200;
const NO_TEXT = "(reasoning omitted)";

const edit = (targetId: string, text: string): SessionBoundaryDraft => ({ type: "context_edit", targetId, replacement: { content: [{ type: "text", text }] } });
const tokens = (chars: number): number => Math.ceil(chars / CHARS_PER_TOKEN);
const blocks = (message: Message): Block[] => (Array.isArray(message.content) ? message.content : []);
const textOf = (message: Message): string => blocks(message).map((block) => block.text ?? "").join("");
const envNumber = (name: string, fallback: number): number => Number(process.env[name]) || fallback;
const charsOf = (content: unknown): number => JSON.stringify(content ?? "", (key, value) => (key === "thinkingSignature" ? undefined : value)).length;
const sizeOf = ({ messages }: Projected): number => tokens(messages.reduce((sum, message) => sum + charsOf(message.content), 0));

const unedited = ({ sourceEntry, messages }: Projected): Message | undefined =>
	messages.length === 1 && JSON.stringify(messages[0].content) === JSON.stringify(sourceEntry.message?.content) ? messages[0] : undefined;

function foldable(entry: Projected): Message | undefined {
	const message = unedited(entry);
	if (message?.role !== "toolResult" || message.isError || NEVER_FOLDED.has(message.toolName ?? "") || !blocks(message).every((block) => block.type === "text")) return;
	const full = textOf(message);
	return full.length >= MIN_RESULT_CHARS && !HANDOFF_LINE.test(full) ? message : undefined;
}

export function planFold(entries: Projected[], branch: Entry[], { keepTokens, skip = new Set() }: { keepTokens: number; skip?: ReadonlySet<string> }): FoldPlan {
	const calls = new Map<string, Block>();
	for (const { messages } of entries)
		for (const message of messages) for (const block of message.role === "assistant" ? blocks(message) : []) if (block.type === "toolCall" && block.id) calls.set(block.id, block);
	let keepStart = entries.length;
	for (let index = entries.length - 1, newest = 0; index >= 0 && (newest += sizeOf(entries[index])) <= keepTokens; index--) keepStart = index;
	const plan: FoldPlan = { drafts: [], targets: [], savedTokens: 0, argChars: 0 };
	const refs = new Map<string, string>();
	const edited = new Set<string>();
	const stash = (callId: string, text: string): { ref: string; full: string } => {
		const stored = branch.find((candidate) => candidate.customType === "result-cap" && candidate.data?.ref === `rc-${callId}`)?.data;
		if (!stored) plan.drafts.push({ type: "custom", customType: "result-cap", data: { ref: `fold-${callId}`, text } });
		return { ref: stored?.ref ?? `fold-${callId}`, full: stored?.text ?? text };
	};
	const lastAssistant = entries.map(({ messages }) => messages[0]?.role).lastIndexOf("assistant");
	for (const [index, entry] of entries.slice(0, keepStart).entries()) {
		const message = unedited(entry);
		if (message?.role !== "assistant" || message.stopReason !== "aborted" || index === lastAssistant || skip.has(entry.sourceEntry.id) || HANDOFF_LINE.test(textOf(message))) continue;
		const used = blocks(message).filter((block) => block.type === "toolCall");
		const results = entries.flatMap((candidate, at) => (used.some((block) => block.id === candidate.messages[0]?.toolCallId) ? [{ at, id: candidate.sourceEntry.id, body: unedited(candidate), size: sizeOf(candidate) }] : []));
		const whole = results.every(({ at, id, body }) => at < keepStart && !skip.has(id) && body && !HANDOFF_LINE.test(textOf(body)) && blocks(body).every((block) => block.type === "text"));
		if (!whole || used.some((block) => NEVER_FOLDED.has(block.name ?? ""))) continue;
		const kept = results.map(({ id, body }) => ({ id, ...stash(body?.toolCallId ?? "", textOf(body as Message)) }));
		const outcome = (block: Block): string => `${block.name} ${JSON.stringify(block.arguments).slice(0, ABORTED_ARGS_CHARS)}: ${results.some(({ body }) => body?.toolCallId === block.id && !body?.isError) ? "done" : "aborted"}`;
		const stub = used.length ? `[abandoned turn: ${used.map(outcome).join(", ")}${kept.length ? `; result_fetch refs: ${kept.map(({ ref }) => ref).join(", ")}` : ""}]` : `[abandoned: ${textOf(message).slice(0, ABORTED_TEXT_CHARS) || NO_TEXT}]`;
		plan.drafts.push(edit(entry.sourceEntry.id, stub));
		for (const { id, ref } of kept) {
			plan.drafts.push({ type: "context_edit", targetId: id, replacement: null });
			refs.set(id, ref);
		}
		for (const id of [entry.sourceEntry.id, ...kept.map(({ id }) => id)]) {
			edited.add(id);
			plan.targets.push(id);
		}
		plan.savedTokens += tokens(JSON.stringify(blocks(message)).length - stub.length) + results.reduce((sum, { size }) => sum + size, 0);
		plan.argChars += used.reduce((sum, block) => sum + JSON.stringify(block.arguments).length, 0);
	}
	for (const entry of entries.slice(0, keepStart)) {
		const message = foldable(entry);
		if (!message || skip.has(entry.sourceEntry.id) || edited.has(entry.sourceEntry.id)) continue;
		const callId = message.toolCallId ?? "";
		const { ref, full } = stash(callId, textOf(message));
		const args = JSON.stringify(calls.get(callId)?.arguments ?? {});
		const stub = `[folded: ${message.toolName} ${args.slice(0, ARGS_CHARS)} -> ${full.length} chars; result_fetch({ref:"${ref}"}) resends it]`;
		plan.drafts.push(edit(entry.sourceEntry.id, stub));
		plan.targets.push(entry.sourceEntry.id);
		refs.set(entry.sourceEntry.id, ref);
		edited.add(entry.sourceEntry.id);
		plan.savedTokens += tokens(textOf(message).length - stub.length);
		plan.argChars += args.length;
	}
	for (const { sourceEntry, messages } of plan.targets.length ? entries : []) {
		const [message] = messages;
		const seen = message?.role === "toolResult" ? receiptEntryId(textOf(message)) : undefined;
		if (seen && refs.has(seen) && !skip.has(sourceEntry.id))
			plan.drafts.push(edit(sourceEntry.id, `unchanged since entry ${seen}, whose result was folded; result_fetch({ref:"${refs.get(seen)}"}) resends it`));
	}
	const first = entries.findIndex((entry) => plan.targets.includes(entry.sourceEntry.id));
	for (const { sourceEntry, messages } of first < 0 ? [] : entries.slice(first)) {
		const [message] = messages;
		if (message?.role !== "assistant" || skip.has(sourceEntry.id) || edited.has(sourceEntry.id)) continue;
		const kept = blocks(message).filter((block) => block.type !== "thinking");
		if (kept.length === blocks(message).length) continue;
		plan.drafts.push(kept.length ? { type: "context_edit", targetId: sourceEntry.id, replacement: { content: kept as unknown as ContextEditableContent } } : edit(sourceEntry.id, NO_TEXT));
		plan.savedTokens += tokens(charsOf(blocks(message)) - charsOf(kept));
	}
	return plan;
}

export function restoreDrafts(entries: Projected[], ids: string[]): SessionBoundaryDraft[] {
	return entries.flatMap(({ sourceEntry }) =>
		ids.includes(sourceEntry.id) && sourceEntry.message?.content ? [{ type: "context_edit" as const, targetId: sourceEntry.id, replacement: { content: sourceEntry.message.content as ContextEditableContent } }] : [],
	);
}

export default function (pi: ExtensionAPI) {
	if (process.env.PI_CONTEXT_CHILD) return;
	let unconfirmed: string[] = [];
	let stopped = false;
	pi.on("turn_end", (event) => {
		if (event.outcome === "completed") unconfirmed = [];
	});
	pi.on("agent_before_settle", (event, ctx) => {
		const mode = process.env.CONTEXT_FOLD ?? DEFAULT_MODE;
		const entries = event.context.contextEntries as unknown as Projected[];
		if (mode === "off") return;
		if (event.outcome === "error" && unconfirmed.length) {
			const reason = ([...event.context.contextMessages] as { errorMessage?: string }[]).reverse().find((message) => message.errorMessage)?.errorMessage ?? "";
			const record = { type: "custom" as const, customType: "context-fold", data: { trigger: "revert", targets: unconfirmed } };
			const drafts = restoreDrafts(entries, unconfirmed);
			unconfirmed = [];
			stopped = true;
			if (ctx.hasUI) ctx.ui.notify(`context-fold: reverted ${drafts.length} folded entries and stopped folding after a rejected request: ${reason.slice(0, ERROR_CHARS)}`, "warning");
			return { entries: [...event.entries, ...drafts, record] };
		}
		if (stopped || event.outcome !== "completed") return;
		const plan = planFold(entries, ctx.sessionManager.getBranch() as unknown as Entry[], { keepTokens: envNumber("CONTEXT_FOLD_KEEP_TOKENS", DEFAULT_KEEP_TOKENS), skip: new Set(event.entries.flatMap((draft) => (draft.type === "context_edit" ? [draft.targetId] : []))) });
		if (plan.savedTokens < envNumber("CONTEXT_FOLD_PENDING_TOKENS", DEFAULT_PENDING_TOKENS)) return;
		const record = { type: "custom" as const, customType: "context-fold", data: { trigger: "run-end", mode, targets: plan.targets, savedTokens: plan.savedTokens, argChars: plan.argChars } };
		if (mode === "on") unconfirmed = plan.drafts.flatMap((draft) => (draft.type === "context_edit" ? [draft.targetId] : []));
		if (ctx.hasUI) ctx.ui.notify(`context-fold: ${mode === "on" ? "folded" : "would fold"} ${plan.targets.length} old tool results, saves ~${plan.savedTokens} tokens`, "info");
		return { entries: [...event.entries, ...(mode === "on" ? plan.drafts : []), record] };
	});
}
