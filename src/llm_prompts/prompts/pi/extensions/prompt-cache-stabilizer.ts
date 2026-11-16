// Keeps the system prompt unchanged between turns so the prompt cache stays valid.
import { getCurrentSystemMessage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const CWD_SECTION = "cwd";
const MOVED_SECTIONS = [CWD_SECTION];
const BUILT_IN_SECTIONS = new Set(["preamble", "tools", "rules", "docs", "addendum", "project_context", "skills", CWD_SECTION]);

type Message = {
	role: string;
	content?: string | unknown[];
	timestamp?: number;
	sections?: Record<string, string | null>;
	toolsAdded?: unknown[];
	toolsRemoved?: unknown[];
};
type Options = { triggered: boolean; since: number };

function isEmptySystemMessage(message: Message): boolean {
	return !message.content?.length && !message.toolsAdded?.length && !message.toolsRemoved?.length;
}

export function stabilizeSystemMessages(messages: Message[], options: Options): Message[] | undefined {
	let changed = false;
	const stabilized = messages.flatMap((message, index) => {
		if (index === 0 || message.role !== "system" || !message.sections) return [message];
		const reAdded = (name: string) =>
			messages.slice(index + 1).some((later) => later.role === "system" && typeof later.sections?.[name] === "string");
		const sections = Object.fromEntries(
			Object.entries(message.sections).filter(
				([name, text]) =>
					text !== null ||
					(!reAdded(name) &&
						(!options.triggered || (message.timestamp ?? 0) <= options.since || BUILT_IN_SECTIONS.has(name))),
			),
		);
		if (Object.keys(sections).length === Object.keys(message.sections).length) return [message];
		changed = true;
		const kept = { ...message, sections };
		return Object.keys(sections).length === 0 && isEmptySystemMessage(message) ? [] : [kept];
	});
	return changed ? stabilized : undefined;
}

export function stabilizeMergedHead(messages: Message[], branchSystemMessages: Message[], options: Options): Message[] | undefined {
	const [head, ...rest] = messages;
	if (head?.role !== "system" || rest.some((message) => message.role === "system")) return undefined;
	if (JSON.stringify(getCurrentSystemMessage(branchSystemMessages as never)?.sections) !== JSON.stringify(head.sections)) return undefined;
	const stabilized = stabilizeSystemMessages(branchSystemMessages, options);
	return stabilized && [{ ...head, sections: getCurrentSystemMessage(stabilized as never)?.sections }, ...rest];
}

export function moveCwdToFirstUserMessage(messages: Message[]): Message[] | undefined {
	const firstUser = messages.findIndex((message) => message.role === "user");
	const latest = (name: string) =>
		messages
			.filter((message) => message.role === "system")
			.reduce<string | undefined>((current, message) => (message.sections && name in message.sections ? (message.sections[name] ?? undefined) : current), undefined);
	const moved = MOVED_SECTIONS.flatMap((name) => {
		const text = latest(name);
		return text === undefined ? [] : [{ type: "text", text }];
	});
	if (firstUser < 0 || moved.length === 0) return undefined;
	return messages.flatMap((message, index) => {
		if (index === firstUser) {
			const text = typeof message.content === "string" ? (message.content ? [{ type: "text", text: message.content }] : []) : (message.content ?? []);
			return [{ ...message, content: [...moved, ...text] }];
		}
		if (message.role !== "system" || !message.sections || !MOVED_SECTIONS.some((name) => name in message.sections!)) return [message];
		const sections = Object.fromEntries(Object.entries(message.sections).filter(([name]) => !MOVED_SECTIONS.includes(name)));
		return index > 0 && Object.keys(sections).length === 0 && isEmptySystemMessage(message) ? [] : [{ ...message, sections }];
	});
}

function foldsSystemMessages(model: { api?: string; compat?: object } | undefined): boolean {
	return (
		model !== undefined &&
		(model.api === "bedrock-converse-stream" ||
			(model.compat as { supportsMidConvoSystemMessages?: boolean } | undefined)?.supportsMidConvoSystemMessages !== true)
	);
}

type Prefix = { system?: unknown; tools?: unknown; toolConfig?: { tools?: unknown } };

export function changedPrefixParts(previous: Record<string, string>, payload: Prefix): { current: Record<string, string>; changed: string[] } {
	const parts = { system: payload.system, tools: payload.toolConfig?.tools ?? payload.tools };
	const current = Object.fromEntries(Object.entries(parts).flatMap(([name, value]) => (value === undefined ? [] : [[name, JSON.stringify(value)]])));
	const names = Object.keys(previous).length === 0 ? [] : [...new Set([...Object.keys(previous), ...Object.keys(current)])];
	return { current, changed: names.filter((name) => previous[name] !== current[name]) };
}

export default function (pi: ExtensionAPI) {
	let previousPrefix: Record<string, string> = {};
	let systemEntries = 0;
	let pendingPrompted = false;
	let triggered = false;
	let lastPromptedAt = 0;

	pi.on("session_start", (_event, ctx) => {
		pendingPrompted = false;
		triggered = false;
		previousPrefix = {};
		systemEntries = 0;
		const lastUser = ctx.sessionManager
			.getBranch()
			.flatMap((entry) => (entry.type === "message" && entry.message.role === "user" ? [entry.message.timestamp] : []))
			.pop();
		lastPromptedAt = lastUser ?? 0;
	});
	pi.on("before_agent_start", () => {
		pendingPrompted = true;
	});
	pi.on("agent_start", () => {
		if (pendingPrompted) lastPromptedAt = Date.now();
		triggered = !pendingPrompted;
		pendingPrompted = false;
	});
	pi.on("before_provider_request", (event, ctx) => {
		const { current, changed } = changedPrefixParts(previousPrefix, event.payload as Prefix);
		if (Object.keys(current).length === 0) return;
		const entries = ctx.sessionManager.getBranch().filter((entry) => entry.type === "message" && entry.message.role === "system").length;
		if (changed.length > 0 && entries === systemEntries) ctx.ui.notify(`prefix changed: ${changed.join("|")}`, "warning");
		previousPrefix = current;
		systemEntries = entries;
	});
	pi.on("context_with_system", (event, ctx) => {
		const eventMessages = event.messages as Message[];
		let stabilized: Message[] | undefined;
		if (foldsSystemMessages(ctx.model)) {
			const options = { triggered, since: lastPromptedAt };
			const branchSystemMessages = ctx.sessionManager
				.getBranch()
				.flatMap((entry) => (entry.type === "message" && entry.message.role === "system" ? [entry.message as Message] : []));
			stabilized = stabilizeSystemMessages(eventMessages, options) ?? stabilizeMergedHead(eventMessages, branchSystemMessages, options);
		}
		const messages = moveCwdToFirstUserMessage(stabilized ?? eventMessages) ?? stabilized;
		return messages && { messages: messages as typeof event.messages };
	});
}
