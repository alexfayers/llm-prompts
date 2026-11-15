// Adds the reload_now tool, which reloads the session after this turn and then continues the task.
// Commands: /reload-now
// Env: PI_HERDSMAN_MAILBOX (set for managed agents, which cannot reload)
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const CONTINUE_MESSAGE = "Reload finished. Continue the task. If nothing is open, reply with one emoji.";
const MANAGED_MESSAGE = "A pi-herdsman managed agent cannot reload. Report the change to your lead instead.";
const RESUMES = Symbol.for("llm-prompts.reload-now");

const resumes = ((globalThis as any)[RESUMES] ??= new Map<string, () => void>()) as Map<string, () => void>;

export default function (pi: ExtensionAPI) {
	let requested = false;

	pi.on("session_start", (event, ctx) => {
		if (event.reason === "reload") resumes.set(ctx.sessionManager.getSessionId(), () => pi.sendUserMessage(CONTINUE_MESSAGE));
	});

	pi.on("agent_settled", (event) => {
		const wanted = requested;
		requested = false;
		if (!wanted || event.aborted) return;
		pi.sendUserMessage("/reload-now", { expandPromptTemplates: true });
	});

	pi.registerTool({
		name: "reload_now",
		label: "Reload now",
		description:
			"Reload extensions, skills, prompts, themes and context files after this turn, then continue the task. Call it alone, as your last action.",
		promptSnippet: "Reload extensions, skills and context files after this turn, then continue",
		parameters: Type.Object({}),
		async execute() {
			if (process.env.PI_HERDSMAN_MAILBOX) throw new Error(MANAGED_MESSAGE);
			requested = true;
			return {
				content: [{ type: "text", text: "Reload requested. Pi reloads after this turn, then sends a message to continue." }],
				details: {},
				terminate: true,
			};
		},
	});

	pi.registerCommand("reload-now", {
		description: "Reload extensions, skills, prompts and context files, then continue the task",
		handler: async (_args, ctx) => {
			if (process.env.PI_HERDSMAN_MAILBOX) {
				ctx.ui.notify(MANAGED_MESSAGE, "error");
				return;
			}
			if (!ctx.isIdle()) {
				requested = true;
				return;
			}
			const id = ctx.sessionManager.getSessionId();
			resumes.delete(id);
			await ctx.reload();
			resumes.get(id)?.();
			resumes.delete(id);
		},
	});
}
