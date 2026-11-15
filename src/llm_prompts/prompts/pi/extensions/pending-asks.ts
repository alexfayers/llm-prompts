// Pins the questions awaiting the user in a widget above the editor, so messages need not restate them.
// Commands: /asks
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const ENTRY_TYPE = "pending-asks";
const WIDGET_KEY = "pending-asks";

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

export default function (pi: ExtensionAPI) {
	const branchEntries = (ctx: ExtensionContext) => ctx.sessionManager.getBranch() as unknown as AskEntry[];

	const refresh = (ctx: ExtensionContext) => {
		if (!ctx.hasUI) return;
		const asks = openAsks(branchEntries(ctx));
		ctx.ui.setWidget(WIDGET_KEY, asks.length ? ["Pending asks", ...lines(asks)] : undefined);
	};

	pi.on("session_start", (_event, ctx) => refresh(ctx));
	pi.on("session_tree", (_event, ctx) => refresh(ctx));

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
				pi.appendEntry(ENTRY_TYPE, { action: "add", id, text: params.text });
			} else {
				if (!openAsks(entries).some((ask) => ask.id === id)) throw new Error(`unknown ask "${id}"`);
				pi.appendEntry(ENTRY_TYPE, { action: "resolve", id });
			}
			refresh(ctx);
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
