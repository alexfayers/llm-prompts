// Keeps the system prompt unchanged between turns so the prompt cache stays valid, and shrinks the agent roster section.
import { getCurrentSystemMessage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const CWD_SECTION = "cwd";
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
	const cwd = messages
		.filter((message) => message.role === "system")
		.reduce<string | undefined>((current, message) => (message.sections && CWD_SECTION in message.sections ? (message.sections[CWD_SECTION] ?? undefined) : current), undefined);
	if (firstUser < 0 || cwd === undefined) return undefined;
	return messages.flatMap((message, index) => {
		if (index === firstUser) {
			const text = typeof message.content === "string" ? (message.content ? [{ type: "text", text: message.content }] : []) : (message.content ?? []);
			return [{ ...message, content: [{ type: "text", text: cwd }, ...text] }];
		}
		if (message.role !== "system" || !message.sections || !(CWD_SECTION in message.sections)) return [message];
		const sections = Object.fromEntries(Object.entries(message.sections).filter(([name]) => name !== CWD_SECTION));
		return index > 0 && Object.keys(sections).length === 0 && isEmptySystemMessage(message) ? [] : [{ ...message, sections }];
	});
}

const ROSTER_SECTION = "agent_definitions";
const ROSTER_FIELDS = ["name", "enabled", "description", "model", "thinking", "noTools", "noBuiltinTools", "tools", "excludeTools", "agents"] as const;

type RosterDefinition = Record<string, unknown>;

function compactDefinition(definition: RosterDefinition): RosterDefinition {
	const excludeTools = Array.isArray(definition.excludeTools) ? definition.excludeTools.filter((tool) => !String(tool).startsWith("mcp__")) : definition.excludeTools;
	const kept: RosterDefinition = { ...definition, excludeTools: Array.isArray(excludeTools) && excludeTools.length === 0 ? undefined : excludeTools };
	return Object.fromEntries(ROSTER_FIELDS.flatMap((field) => (kept[field] === undefined ? [] : [[field, kept[field]]])));
}

export function compactRoster(content: string): string {
	const split = content.indexOf("\n\n");
	if (split < 0) return content;
	let definitions: unknown;
	try {
		definitions = JSON.parse(content.slice(0, split));
	} catch {
		return content;
	}
	if (!Array.isArray(definitions) || !definitions.every((definition) => typeof definition?.name === "string")) return content;
	const lines = definitions.map((definition) => `  ${JSON.stringify(compactDefinition(definition))}`);
	return `[\n${lines.join(",\n")}\n]${content.slice(split)}`;
}

const ROSTER_WRAPPER = /^<agent_definitions>\n([\s\S]*)\n<\/agent_definitions>$/;

export function compactRosterSections(messages: Message[]): Message[] | undefined {
	let changed = false;
	const compacted = messages.map((message) => {
		const section = message.role === "system" ? message.sections?.[ROSTER_SECTION] : undefined;
		const content = typeof section === "string" ? ROSTER_WRAPPER.exec(section)?.[1] : undefined;
		if (content === undefined) return message;
		const roster = `<${ROSTER_SECTION}>\n${compactRoster(content)}\n</${ROSTER_SECTION}>`;
		if (roster === section) return message;
		changed = true;
		return { ...message, sections: { ...message.sections, [ROSTER_SECTION]: roster } };
	});
	return changed ? compacted : undefined;
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
		const eventMessages = event.messages as Message[];
		let stabilized: Message[] | undefined;
		if (foldsSystemMessages(ctx.model)) {
			const options = { triggered, since: lastPromptedAt };
			const branchSystemMessages = ctx.sessionManager
				.getBranch()
				.flatMap((entry) => (entry.type === "message" && entry.message.role === "system" ? [entry.message as Message] : []));
			stabilized = stabilizeSystemMessages(eventMessages, options) ?? stabilizeMergedHead(eventMessages, branchSystemMessages, options);
		}
		const moved = moveCwdToFirstUserMessage(stabilized ?? eventMessages) ?? stabilized;
		const messages = compactRosterSections(moved ?? eventMessages) ?? moved;
		return messages && { messages: messages as typeof event.messages };
	});
}
