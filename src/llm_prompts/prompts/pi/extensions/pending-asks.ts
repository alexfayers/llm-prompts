// Pins the questions awaiting the user in a widget above the editor, so messages need not restate them, resolves them when the user answers an ask_user call, and restores the restate rule when there is no UI.
// Commands: /answer [<id> [<text>]] (also ctrl+shift+a)
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const ENTRY_TYPE = "pending-asks";
const WIDGET_KEY = "pending-asks";
const RULE_TYPE = "pending-asks-rule";
const REMIND_TYPE = "pending-asks-remind";
const REMIND_TURNS = 5;
const ANSWER_SHORTCUT = "ctrl+shift+a";
const ASK_USER_TOOL = "ask_user";
const RESTATE_RULE = `Where something awaits the user's decision, MUST restate EVERY pending ask in full in each message until it is answered - MUST NOT back-reference them ("the two from earlier", "the previous proposal").`;

type AskEntry = { type: string; customType?: string; message?: { role?: string }; data?: { action?: "add" | "resolve"; id?: string; text?: string } };
type Ask = { id: string; text: string };

/** The asks added and not yet resolved on the branch, oldest first. */
export function openAsks(entries: AskEntry[]): Ask[] {
	const open = new Map<string, Ask>();
	for (const { type, customType, data } of entries) {
		if (type !== "custom" || customType !== ENTRY_TYPE || !data?.id) continue;
		if (data.action === "add") open.set(data.id, { id: data.id, text: data.text ?? "" });
		else open.delete(data.id);
	}
	return [...open.values()];
}

const lines = (asks: Ask[]): string[] => asks.map((ask) => `${ask.id}: ${ask.text}`);

/** The open asks of the branch, one per line, as the bare word `asks` shows them. */
export const listAsks = (entries: AskEntry[]): string => lines(openAsks(entries)).join("\n") || "no pending asks";

const nextId = (entries: AskEntry[]): string => `a${entries.filter((entry) => entry.customType === ENTRY_TYPE && entry.data?.action === "add").length + 1}`;

type AskContext = Pick<ExtensionContext, "hasUI" | "ui" | "sessionManager">;
const branchEntries = (ctx: Pick<ExtensionContext, "sessionManager">) => ctx.sessionManager.getBranch() as unknown as AskEntry[];

const refresh = (ctx: AskContext) => {
	if (!ctx.hasUI) return;
	const asks = openAsks(branchEntries(ctx));
	ctx.ui.setWidget(WIDGET_KEY, asks.length ? [`Pending asks - /answer or ${ANSWER_SHORTCUT}`, ...lines(asks)] : undefined);
};

function pinAsk(pi: Pick<ExtensionAPI, "appendEntry">, ctx: AskContext, id: string, text: string): void {
	pi.appendEntry(ENTRY_TYPE, { action: "add", id, text });
	refresh(ctx);
}

const resolveAsk = (pi: Pick<ExtensionAPI, "appendEntry">, ctx: AskContext, id: string) => {
	pi.appendEntry(ENTRY_TYPE, { action: "resolve", id });
	refresh(ctx);
};

/** The reminder of the open asks, once this prompt is at least `REMIND_TURNS` user turns after the last reminder or the oldest open ask. */
function reminder(entries: AskEntry[]): string | undefined {
	const asks = openAsks(entries);
	if (!asks.length) return undefined;
	const since = entries
		.map((entry) => entry.customType === REMIND_TYPE || (entry.customType === ENTRY_TYPE && entry.data?.action === "add" && entry.data.id === asks[0].id))
		.lastIndexOf(true);
	const turns = entries.slice(since + 1).filter((entry) => entry.type === "message" && entry.message?.role === "user").length + 1;
	if (turns < REMIND_TURNS) return undefined;
	return `[asks] still open: ${asks.map((ask) => ask.id).join(", ")}. Resolve any you have answered, re-ask through ask_user any that block work, and leave the rest.`;
}

async function answer(pi: ExtensionAPI, ctx: AskContext, args: string): Promise<void> {
	const asks = openAsks(branchEntries(ctx));
	if (!asks.length) return ctx.ui.notify("no pending asks", "info");
	const [, id = "", given = ""] = args.trim().match(/^(\S*)\s*([\s\S]*)$/) ?? [];
	let ask = asks.find((open) => open.id === id);
	if (id && !ask) return ctx.ui.notify(`unknown ask "${id}"`, "error");
	if (!ask) ask = asks[lines(asks).indexOf((await ctx.ui.select("Answer which ask?", lines(asks))) ?? "")];
	if (!ask) return;
	const reply = given || ((await ctx.ui.input(`Answer to ${ask.id}: ${ask.text}`)) ?? "").trim();
	if (!reply) return;
	resolveAsk(pi, ctx, ask.id);
	pi.sendUserMessage(`Answer to ${ask.id}: ${reply}`, { deliverAs: "followUp" });
}

export default function (pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => refresh(ctx));
	pi.on("session_tree", (_event, ctx) => refresh(ctx));

	const openBeforeAskUser = new Map<string, string[]>();
	pi.on("tool_call", (event, ctx) => {
		if (event.toolName === ASK_USER_TOOL) openBeforeAskUser.set(event.toolCallId, openAsks(branchEntries(ctx)).map((ask) => ask.id));
	});

	pi.on("tool_result", (event, ctx) => {
		const answered = openBeforeAskUser.get(event.toolCallId);
		openBeforeAskUser.delete(event.toolCallId);
		if (answered && !event.isError && !(event.details as { cancelled?: boolean } | undefined)?.cancelled) {
			const open = new Set(openAsks(branchEntries(ctx)).map((ask) => ask.id));
			for (const id of answered) if (open.has(id)) resolveAsk(pi, ctx, id);
		}
	});

	pi.on("before_agent_start", (_event, ctx) => {
		const remind = reminder(branchEntries(ctx));
		if (remind) return { message: { customType: REMIND_TYPE, content: remind, display: false } };
	});

	pi.on("before_agent_start", (_event, ctx) => {
		if (ctx.hasUI || branchEntries(ctx).some((entry) => entry.customType === RULE_TYPE)) return undefined;
		return { message: { customType: RULE_TYPE, content: `${RESTATE_RULE} This overrides any rule against restating pinned asks.`, display: false } };
	});

	pi.registerTool({
		name: "asks",
		label: "Asks",
		description: "Pin an action or decision only the user can take (add, with an optional id, returning the id), or remove it by that id once answered (resolve). Pinned asks show above the editor.",
		parameters: Type.Object({
			action: Type.Union([Type.Literal("add"), Type.Literal("resolve")]),
			text: Type.Optional(Type.String()),
			id: Type.Optional(Type.String({ description: "The id to add the ask as, or of the ask to resolve" })),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const entries = branchEntries(ctx);
			let id = params.id ?? "";
			if (params.action === "add") {
				if (!params.text) throw new Error("add needs text");
				id ||= nextId(entries);
				pinAsk(pi, ctx, id, params.text);
			} else {
				if (!openAsks(entries).some((ask) => ask.id === id)) throw new Error(`unknown ask "${id}"`);
				resolveAsk(pi, ctx, id);
			}
			return { content: [{ type: "text" as const, text: `ask ${id} ${params.action === "add" ? "pinned" : "resolved"}` }], details: {} };
		},
	});

	pi.registerCommand("answer", {
		description: "Answer a pending ask: /answer [<id> [<text>]]",
		handler: (args, ctx) => answer(pi, ctx, args),
	});

	pi.registerShortcut(ANSWER_SHORTCUT, {
		description: "Answer a pending ask",
		handler: (ctx) => answer(pi, ctx, ""),
	});
}
