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

	const notify = (ctx: ExtensionContext, message: string, level: "info" | "error") => {
		if (ctx.hasUI) ctx.ui.notify(message, level);
	};

	pi.on("session_before_compact", (event) => {
		const summary = pendingSummary;
		pendingSummary = undefined;
		if (summary === undefined || event.customInstructions !== summary) return;
		return {
			compaction: {
				summary,
				firstKeptEntryId: event.preparation.firstKeptEntryId,
				tokensBefore: event.preparation.tokensBefore,
			},
		};
	});

	pi.registerTool({
		name: "compact_now",
		label: "Compact now",
		description:
			"Compact this session's context now. `instructions` is the summary that replaces the old context. It MUST name the open tasks, asks and decisions. The session continues automatically after compaction.",
		promptSnippet: "Compact the session context with a model-written summary",
		parameters: PARAMETERS,
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			pendingSummary = params.instructions;
			notify(ctx, "Compaction started", "info");
			ctx.compact({
				customInstructions: params.instructions,
				onComplete: () => {
					notify(ctx, "Compaction completed", "info");
					pi.sendUserMessage(CONTINUE_MESSAGE, { deliverAs: "followUp" });
				},
				onError: (error) => {
					pendingSummary = undefined;
					notify(ctx, `Compaction failed: ${error.message}`, "error");
				},
			});
			return { content: [{ type: "text", text: "Compaction started." }], details: {} };
		},
	});
}
