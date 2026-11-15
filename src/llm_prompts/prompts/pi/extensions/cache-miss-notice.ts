// Tells the model about a large prompt cache miss and its likely cause, by adding one line to the next tool result.
// Env: PI_CACHE_RETENTION (long means a one hour cache, otherwise five minutes)
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { changedPrefixParts } from "./prompt-cache-stabilizer.ts";

/** The cache-write and missed tokens that count as a miss. */
const MISS_TOKENS = 20_000;

type Usage = { input: number; cacheRead: number; cacheWrite: number; cost?: { input: number; cacheRead: number; cacheWrite: number } };
type Request = { usage: Usage; timestamp: number };
type Entry = {
	type: string;
	timestamp?: string;
	kind?: string;
	usage?: Usage;
	thinkingLevel?: string;
	modelId?: string;
	message?: { role: string; usage?: Usage; timestamp?: number };
};

const PREFIX_NAMES: Record<string, string> = { system: "system prompt", tools: "tool list" };

const cacheTtlMs = () => (process.env.PI_CACHE_RETENTION === "long" ? 60 : 5) * 60_000;

const asRequest = (entry: Entry): Request | undefined => {
	if (entry.type === "usage" && entry.kind === "cache_warm" && entry.usage) return { usage: entry.usage, timestamp: Date.parse(entry.timestamp ?? "") };
	if (entry.type === "message" && entry.message?.role === "assistant" && entry.message.usage) return { usage: entry.message.usage, timestamp: entry.message.timestamp ?? 0 };
};

const entryCause = (entry: Entry): string | undefined => {
	if (entry.type === "thinking_level_change") return `a thinking level change to ${entry.thinkingLevel}`;
	if (entry.type === "model_change") return `a model change to ${entry.modelId}`;
	if (entry.type === "compaction" || entry.type === "branch_summary") return "a compaction";
	if (entry.type === "message" && entry.message?.role === "system") return "a system prompt change";
};

function findMiss(entries: Entry[], current: Request, prefixChanges: string[] = []): string | undefined {
	const start = entries.map((entry) => Boolean(asRequest(entry))).lastIndexOf(true);
	if (start < 0) return;
	const prev = asRequest(entries[start])!;
	const { usage } = current;
	const missed = Math.min(prev.usage.input + prev.usage.cacheRead + prev.usage.cacheWrite, usage.input + usage.cacheRead + usage.cacheWrite) - usage.cacheRead;
	if (usage.cacheWrite < MISS_TOKENS || missed < MISS_TOKENS) return;
	const gap = current.timestamp - prev.timestamp;
	const cause =
		entries.slice(start + 1).map(entryCause).filter(Boolean).at(-1) ??
		(prefixChanges.length > 0 ? `a ${prefixChanges.map((part) => PREFIX_NAMES[part] ?? part).join(" and ")} change` : undefined) ??
		(gap > cacheTtlMs() ? `a ${Math.round(gap / 60_000)} min idle gap` : "cause unknown");
	const paid = usage.input + usage.cacheWrite;
	const cost = usage.cost && paid > 0 && usage.cacheRead > 0 ? missed * Math.max(0, (usage.cost.input + usage.cost.cacheWrite) / paid - usage.cost.cacheRead / usage.cacheRead) : undefined;
	const price = cost === undefined ? "" : ` (~$${cost.toFixed(2)})`;
	return `[cache] miss: ${Math.round(missed / 1000)}k re-written${price} after ${cause}. If an extension or your own action caused it, fix that.`;
}

export default function (pi: ExtensionAPI) {
	let previousPrefix: Record<string, string> = {};
	let prefixChanges: string[] = [];
	let pending: string | undefined;
	pi.on("before_provider_request", (event) => {
		const { current, changed } = changedPrefixParts(previousPrefix, event.payload as never);
		if (Object.keys(current).length === 0) return;
		previousPrefix = current;
		prefixChanges = changed;
	});
	pi.on("message_end", (event, ctx) => {
		const message = event.message as { role: string; usage?: Usage; timestamp?: number };
		if (message.role !== "assistant" || !message.usage) return;
		pending = findMiss(ctx.sessionManager.getBranch() as Entry[], { usage: message.usage, timestamp: message.timestamp ?? Date.now() }, prefixChanges) ?? pending;
	});
	pi.on("turn_end", () => {
		pending = undefined;
	});
	pi.on("tool_result", (event) => {
		if (event.parentToolCallId || !pending) return;
		const text = pending;
		pending = undefined;
		return { content: [...event.content, { type: "text" as const, text }], structuredContent: event.structuredContent };
	});
}
