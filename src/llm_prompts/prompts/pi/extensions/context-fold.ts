// Folds old tool results into short stubs at the end of a run, keeping their full text fetchable with result_fetch.
// Env: CONTEXT_FOLD (on, dry to only record what it would fold, or off; default on), CONTEXT_FOLD_PENDING_TOKENS (tokens a fold must save, default 30000), CONTEXT_FOLD_KEEP_TOKENS (newest tokens never folded, default 40000)
import type { ContextEditableContent, ExtensionAPI, SessionBoundaryDraft } from "@earendil-works/pi-coding-agent";
import { receiptEntryId } from "./already-seen.ts";
import { HANDOFF_LINE } from "./result-cap.ts";

type Block = { type: string; id?: string; name?: string; text?: string; thinking?: string; arguments?: unknown };
type Message = { role: string; content?: string | Block[]; toolCallId?: string; toolName?: string; isError?: boolean };
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
const NO_TEXT = "(reasoning omitted)";

const edit = (targetId: string, text: string): SessionBoundaryDraft => ({ type: "context_edit", targetId, replacement: { content: [{ type: "text", text }] } });
const tokens = (chars: number): number => Math.ceil(chars / CHARS_PER_TOKEN);
const blocks = (message: Message): Block[] => (Array.isArray(message.content) ? message.content : []);
const textOf = (message: Message): string => blocks(message).map((block) => block.text ?? "").join("");
const envNumber = (name: string, fallback: number): number => Number(process.env[name]) || fallback;
const sizeOf = ({ messages }: Projected): number => tokens(messages.reduce((sum, message) => sum + JSON.stringify(message.content ?? "").length, 0));

function foldable({ sourceEntry, messages }: Projected): Message | undefined {
	const [message] = messages;
	if (messages.length !== 1 || message?.role !== "toolResult" || message.isError || NEVER_FOLDED.has(message.toolName ?? "") || !blocks(message).every((block) => block.type === "text")) return;
	const full = textOf(message);
	return JSON.stringify(message.content) === JSON.stringify(sourceEntry.message?.content) && full.length >= MIN_RESULT_CHARS && !HANDOFF_LINE.test(full) ? message : undefined;
}

export function planFold(entries: Projected[], branch: Entry[], { keepTokens }: { keepTokens: number }): FoldPlan {
	const calls = new Map<string, Block>();
	for (const { messages } of entries)
		for (const message of messages) for (const block of message.role === "assistant" ? blocks(message) : []) if (block.type === "toolCall" && block.id) calls.set(block.id, block);
	let keepStart = entries.length;
	for (let index = entries.length - 1, newest = 0; index >= 0 && (newest += sizeOf(entries[index])) <= keepTokens; index--) keepStart = index;
	const plan: FoldPlan = { drafts: [], targets: [], savedTokens: 0, argChars: 0 };
	const refs = new Map<string, string>();
	for (const entry of entries.slice(0, keepStart)) {
		const message = foldable(entry);
		if (!message) continue;
		const callId = message.toolCallId ?? "";
		const stored = branch.find((candidate) => candidate.customType === "result-cap" && candidate.data?.ref === `rc-${callId}`)?.data;
		const full = stored?.text ?? textOf(message);
		const ref = stored?.ref ?? `fold-${callId}`;
		const args = JSON.stringify(calls.get(callId)?.arguments ?? {});
		const stub = `[folded: ${message.toolName} ${args.slice(0, ARGS_CHARS)} -> ${full.length} chars; result_fetch({ref:"${ref}"}) resends it]`;
		if (!stored) plan.drafts.push({ type: "custom", customType: "result-cap", data: { ref, text: full } });
		plan.drafts.push(edit(entry.sourceEntry.id, stub));
		plan.targets.push(entry.sourceEntry.id);
		refs.set(entry.sourceEntry.id, ref);
		plan.savedTokens += tokens(textOf(message).length - stub.length);
		plan.argChars += args.length;
	}
	for (const { sourceEntry, messages } of plan.targets.length ? entries : []) {
		const [message] = messages;
		const seen = message?.role === "toolResult" ? receiptEntryId(textOf(message)) : undefined;
		if (seen && refs.has(seen))
			plan.drafts.push(edit(sourceEntry.id, `unchanged since entry ${seen}, whose result was folded; result_fetch({ref:"${refs.get(seen)}"}) resends it`));
	}
	const first = entries.findIndex((entry) => plan.targets.includes(entry.sourceEntry.id));
	for (const { sourceEntry, messages } of first < 0 ? [] : entries.slice(first)) {
		const [message] = messages;
		if (message?.role !== "assistant") continue;
		const kept = blocks(message).filter((block) => block.type !== "thinking");
		if (kept.length === blocks(message).length) continue;
		plan.drafts.push(kept.length ? { type: "context_edit", targetId: sourceEntry.id, replacement: { content: kept as unknown as ContextEditableContent } } : edit(sourceEntry.id, NO_TEXT));
		plan.savedTokens += tokens(JSON.stringify(blocks(message)).length - JSON.stringify(kept).length);
	}
	return plan;
}

export default function (pi: ExtensionAPI) {
	if (process.env.PI_CONTEXT_CHILD) return;
	pi.on("agent_before_settle", (event, ctx) => {
		const mode = process.env.CONTEXT_FOLD ?? DEFAULT_MODE;
		if (mode === "off" || event.outcome !== "completed") return;
		const plan = planFold(event.context.contextEntries as unknown as Projected[], ctx.sessionManager.getBranch() as unknown as Entry[], { keepTokens: envNumber("CONTEXT_FOLD_KEEP_TOKENS", DEFAULT_KEEP_TOKENS) });
		if (plan.savedTokens < envNumber("CONTEXT_FOLD_PENDING_TOKENS", DEFAULT_PENDING_TOKENS)) return;
		const record = { type: "custom" as const, customType: "context-fold", data: { trigger: "run-end", mode, targets: plan.targets, savedTokens: plan.savedTokens, argChars: plan.argChars } };
		if (ctx.hasUI) ctx.ui.notify(`context-fold: ${mode === "on" ? "folded" : "would fold"} ${plan.targets.length} old tool results, saves ~${plan.savedTokens} tokens`, "info");
		return { entries: [...event.entries, ...(mode === "on" ? plan.drafts : []), record] };
	});
}
