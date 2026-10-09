// Keeps the system prompt unchanged between turns so the prompt cache stays valid.
import { getCurrentSystemMessage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BUILT_IN_SECTIONS = new Set(["preamble", "tools", "rules", "docs", "addendum", "project_context", "skills", "cwd"]);

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

function foldsSystemMessages(model: { api?: string; compat?: object } | undefined): boolean {
	return (
		model !== undefined &&
		(model.api === "bedrock-converse-stream" ||
			(model.compat as { supportsMidConvoSystemMessages?: boolean } | undefined)?.supportsMidConvoSystemMessages !== true)
	);
}

export default function (pi: ExtensionAPI) {
	let pendingPrompted = false;
	let triggered = false;
	let lastPromptedAt = 0;

	pi.on("session_start", (_event, ctx) => {
		pendingPrompted = false;
		triggered = false;
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
	pi.on("context_with_system", (event, ctx) => {
		if (!foldsSystemMessages(ctx.model)) return undefined;
		const options = { triggered, since: lastPromptedAt };
		const branchSystemMessages = ctx.sessionManager
			.getBranch()
			.flatMap((entry) => (entry.type === "message" && entry.message.role === "system" ? [entry.message as Message] : []));
		const eventMessages = event.messages as Message[];
		const messages =
			stabilizeSystemMessages(eventMessages, options) ?? stabilizeMergedHead(eventMessages, branchSystemMessages, options);
		return messages && { messages: messages as typeof event.messages };
	});
}
