// Adds the compact_now tool, which ends the turn, replaces the session context with a summary and then continues the task.
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const PARAMETERS = Type.Object({
	instructions: Type.String({
		description: "Summary the compacted context is replaced by. Name the open tasks, asks and decisions.",
	}),
});

const CONTINUE_MESSAGE =
	"Compaction finished. Continue the task from the summary. If nothing is open, reply with one emoji.";

export default function (pi: ExtensionAPI) {
	let pendingSummary: string | undefined;
	let requested: string | undefined;
	let callResultEntryId: string | undefined;

	const notify = (ctx: ExtensionContext, message: string, level: "info" | "error" = "info") => {
		if (ctx.hasUI) ctx.ui.notify(message, level);
	};

	pi.on("session_before_compact", (event) => {
		const summary = pendingSummary;
		pendingSummary = undefined;
		if (summary === undefined || event.customInstructions !== summary) return;
		const entries = event.branchEntries;
		const callIndex = entries.findIndex((entry) => entry.id === callResultEntryId);
		const entryAfterCall = callIndex < 0 ? undefined : entries[callIndex + 1];
		const isLaterCut =
			entryAfterCall !== undefined &&
			!(entryAfterCall.type === "message" && entryAfterCall.message.role === "toolResult") &&
			entries.findIndex((entry) => entry.id === entryAfterCall.id) >
				entries.findIndex((entry) => entry.id === event.preparation.firstKeptEntryId);
		return {
			compaction: {
				summary,
				firstKeptEntryId: isLaterCut ? entryAfterCall.id : event.preparation.firstKeptEntryId,
				tokensBefore: event.preparation.tokensBefore,
			},
		};
	});

	pi.on("turn_end", (event, ctx) => {
		const instructions = requested;
		const callIndex = event.toolResults.findIndex((result) => result.toolName === "compact_now");
		if (instructions === undefined || callIndex < 0) return;
		requested = undefined;
		callResultEntryId = event.toolResultEntryIds[callIndex];
		pendingSummary = instructions;
		notify(ctx, "Compaction started");
		ctx.compact({
			customInstructions: instructions,
			onComplete: () => {
				notify(ctx, "Compaction completed");
				pi.sendUserMessage(CONTINUE_MESSAGE, { deliverAs: "followUp" });
			},
			onError: (error) => {
				pendingSummary = undefined;
				notify(ctx, `Compaction failed: ${error.message}`, "error");
				pi.sendUserMessage(`Compaction failed: ${error.message}. Continue the task.`, { deliverAs: "followUp" });
			},
		});
	});

	pi.registerTool({
		name: "compact_now",
		label: "Compact now",
		description:
			"Compact this session's context. It ends the turn at once. `instructions` is the summary that replaces the old context. It MUST name the open tasks, asks and decisions. Messages that arrive later stay in context. The session continues automatically after compaction.",
		promptSnippet: "Compact the session context with a model-written summary",
		parameters: PARAMETERS,
		async execute(_toolCallId, params) {
			requested = params.instructions;
			return {
				content: [{ type: "text", text: "Compaction requested. The turn ends and pi compacts now, then sends a message to continue." }],
				details: {},
				terminate: true,
			};
		},
	});
}
