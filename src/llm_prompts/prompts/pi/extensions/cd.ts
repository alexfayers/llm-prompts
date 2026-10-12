// Adds /cd and the change_dir tool, which move the session (history kept) to another working directory.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const PARAMETERS = Type.Object({
	path: Type.String({ description: "Directory to move the session to. Relative paths resolve against the current directory." }),
});

const CONTINUE_MESSAGE = "Directory changed. Continue the task.";
const NOT_SAVED_MESSAGE = "The session is not saved, so it cannot move.";

const notify = (ctx: ExtensionContext, message: string, level: "info" | "error") => {
	if (ctx.hasUI) ctx.ui.notify(message, level);
};

const resolveTarget = (cwd: string, input: string): string => path.resolve(cwd, input.replace(/^~(?=$|\/)/, os.homedir()));

const isDirectory = (target: string): boolean => fs.statSync(target, { throwIfNoEntry: false })?.isDirectory() === true;

function sessionFileIn(target: string, sessionDir: string | undefined, sourceFile: string | undefined): string {
	if (sourceFile && fs.existsSync(sourceFile)) return SessionManager.forkFrom(sourceFile, target, sessionDir).getSessionFile()!;
	const fresh = SessionManager.create(target, sessionDir);
	const file = fresh.getSessionFile()!;
	fs.writeFileSync(file, `${JSON.stringify(fresh.getHeader())}\n`);
	return file;
}

export default function (pi: ExtensionAPI) {
	let pendingTarget: string | undefined;
	let continueTarget: string | undefined;

	pi.on("agent_settled", (event) => {
		const target = pendingTarget;
		pendingTarget = undefined;
		if (target === undefined || event.aborted) return;
		continueTarget = target;
		pi.sendUserMessage(`/cd ${target}`, { expandPromptTemplates: true });
	});

	pi.registerTool({
		name: "change_dir",
		label: "Change directory",
		description:
			"Move this session, with its history, to another working directory. The switch happens after the current turn, then the task continues there.",
		promptSnippet: "Move the session to another working directory",
		parameters: PARAMETERS,
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			if (!ctx.sessionManager.getSessionFile()) throw new Error(NOT_SAVED_MESSAGE);
			const target = resolveTarget(ctx.cwd, params.path);
			if (!isDirectory(target)) throw new Error(`Not a directory: ${target}`);
			pendingTarget = target;
			return { content: [{ type: "text", text: `Moving to ${target} after this turn.` }], details: {} };
		},
	});

	pi.registerCommand("cd", {
		description: "Move this session (history kept) to another working directory",
		handler: async (args: string, ctx: ExtensionCommandContext) => {
			const input = args.trim();
			const target = resolveTarget(ctx.cwd, input);
			const continueTask = target === continueTarget;
			continueTarget = undefined;
			if (input === "") {
				notify(ctx, "Usage: /cd <dir>", "error");
				return;
			}
			if (!ctx.sessionManager.getSessionFile()) {
				notify(ctx, NOT_SAVED_MESSAGE, "error");
				return;
			}
			if (target === ctx.cwd) {
				notify(ctx, `Already in ${target}`, "info");
				return;
			}
			if (!isDirectory(target)) {
				notify(ctx, `Not a directory: ${target}`, "error");
				return;
			}
			const sessions = ctx.sessionManager as SessionManager;
			const sessionDir = sessions.usesDefaultSessionDir() ? undefined : sessions.getSessionDir();
			const sessionFile = sessionFileIn(target, sessionDir, sessions.getSessionFile());
			const { cancelled } = await ctx.switchSession(sessionFile, {
				withSession: async (replaced) => {
					if (continueTask) await replaced.sendUserMessage(CONTINUE_MESSAGE);
				},
			});
			if (cancelled) {
				fs.rmSync(sessionFile, { force: true });
				notify(ctx, "Directory change cancelled", "info");
			}
		},
	});
}
