// Pins the questions awaiting the user in a widget above the editor, so messages need not restate them, and restores the restate rule when there is no UI.
// Commands: /asks
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const ENTRY_TYPE = "pending-asks";
const WIDGET_KEY = "pending-asks";
const RULE_TYPE = "pending-asks-rule";
export const RESTATE_RULE = `Where something awaits the user's decision, MUST restate EVERY pending ask in full in each message until it is answered - MUST NOT back-reference them ("the two from earlier", "the previous proposal").`;

type AskEntry = { type: string; customType?: string; data?: { action?: "add" | "resolve"; id?: string; text?: string } };
export type Ask = { id: string; text: string };

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

const nextId = (entries: AskEntry[]): string => `a${entries.filter((entry) => entry.customType === ENTRY_TYPE && entry.data?.action === "add").length + 1}`;

type AskContext = Pick<ExtensionContext, "hasUI" | "ui" | "sessionManager">;
const branchEntries = (ctx: Pick<ExtensionContext, "sessionManager">) => ctx.sessionManager.getBranch() as unknown as AskEntry[];

const refresh = (ctx: AskContext) => {
	if (!ctx.hasUI) return;
	const asks = openAsks(branchEntries(ctx));
	ctx.ui.setWidget(WIDGET_KEY, asks.length ? ["Pending asks", ...lines(asks)] : undefined);
};

/** Pins an ask under the given id, as the `asks` tool's add does. */
export function pinAsk(pi: Pick<ExtensionAPI, "appendEntry">, ctx: AskContext, id: string, text: string): void {
	pi.appendEntry(ENTRY_TYPE, { action: "add", id, text });
	refresh(ctx);
}

export default function (pi: ExtensionAPI) {

	pi.on("session_start", (_event, ctx) => refresh(ctx));
	pi.on("session_tree", (_event, ctx) => refresh(ctx));

	pi.on("before_agent_start", (_event, ctx) => {
		if (ctx.hasUI || branchEntries(ctx).some((entry) => entry.customType === RULE_TYPE)) return undefined;
		return { message: { customType: RULE_TYPE, content: `${RESTATE_RULE} This overrides any rule against restating pinned asks.`, display: false } };
	});

	pi.registerTool({
		name: "asks",
		label: "Asks",
		description: "Pin a question that awaits the user (add), or remove it once answered (resolve). Pinned asks show above the editor.",
		parameters: Type.Object({
			action: Type.Union([Type.Literal("add"), Type.Literal("resolve")]),
			text: Type.Optional(Type.String()),
			id: Type.Optional(Type.String()),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const entries = branchEntries(ctx);
			let id = params.id ?? "";
			if (params.action === "add") {
				if (!params.text) throw new Error("add needs text");
				id = nextId(entries);
				pinAsk(pi, ctx, id, params.text);
			} else {
				if (!openAsks(entries).some((ask) => ask.id === id)) throw new Error(`unknown ask "${id}"`);
				pi.appendEntry(ENTRY_TYPE, { action: "resolve", id });
				refresh(ctx);
			}
			return { content: [{ type: "text" as const, text: `ask ${id} ${params.action === "add" ? "pinned" : "resolved"}` }], details: {} };
		},
	});

	pi.registerCommand("asks", {
		description: "List the pending asks without a model call",
		handler: async (_args, ctx) => {
			const asks = openAsks(branchEntries(ctx));
			ctx.ui.notify(asks.length ? lines(asks).join("\n") : "no pending asks", "info");
		},
	});
}
