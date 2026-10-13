// Adds /cd and the change_dir tool, which move the session (history kept) to another working directory.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { getAgentDir, SessionManager } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const PARAMETERS = Type.Object({
	path: Type.String({ description: "Directory to move the session to. Relative paths resolve against the current directory." }),
});

const CONTINUE_MESSAGE = "Directory changed. Continue the task.";
const MAILBOX_DIR = path.join("pi-herdsman", "runtime", "mailboxes-v5");

function ownedAgentLabels(ownerSessionId: string): string[] {
	const root = path.join(getAgentDir(), MAILBOX_DIR);
	const labels: string[] = [];
	for (const name of fs.existsSync(root) ? fs.readdirSync(root) : []) {
		const state = JSON.parse(fs.readFileSync(path.join(root, name, "state.json"), "utf8"));
		if (state.ownerSessionId === ownerSessionId) labels.push(String(state.agentLabel ?? name));
	}
	return labels.sort();
}

// Returns the reason the session cannot move to target, or undefined where it can.
function checkTarget(ctx: ExtensionContext, target: string): string | undefined {
	if (process.env.PI_HERDSMAN_MAILBOX) return "A pi-herdsman managed agent cannot change directory.";
	let labels: string[];
	try {
		labels = ownedAgentLabels(ctx.sessionManager.getSessionId());
	} catch {
		return "Cannot read pi-herdsman agent state, so the session cannot move.";
	}
	if (labels.length > 0) return `Cannot move while this session owns pi-herdsman agents: ${labels.join(", ")}. Close them with close_agent, then retry.`;
	if (!ctx.sessionManager.getSessionFile()) return "The session is not saved, so it cannot move.";
	if (target === ctx.cwd) return `Already in ${target}`;
	if (!fs.statSync(target, { throwIfNoEntry: false })?.isDirectory()) return `Not a directory: ${target}`;
	return undefined;
}

const resolveTarget = (cwd: string, input: string): string => path.resolve(cwd, input.replace(/^~(?=$|\/)/, os.homedir()));

function sessionFileIn(target: string, sessions: SessionManager): string {
	const sessionDir = sessions.usesDefaultSessionDir() ? undefined : sessions.getSessionDir();
	const source = sessions.getSessionFile();
	if (source && fs.existsSync(source)) return SessionManager.forkFrom(source, target, sessionDir).getSessionFile()!;
	const fresh = SessionManager.create(target, sessionDir);
	fs.writeFileSync(fresh.getSessionFile()!, `${JSON.stringify(fresh.getHeader())}\n`);
	return fresh.getSessionFile()!;
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
			if (!ctx.hasUI) throw new Error("change_dir needs a session with a UI. In print or JSON mode, start pi in the target directory instead.");
			const target = resolveTarget(ctx.cwd, params.path);
			const blocked = checkTarget(ctx, target);
			if (blocked) throw new Error(blocked);
			pendingTarget = target;
			return { content: [{ type: "text", text: `Moving to ${target} after this turn.` }], details: {} };
		},
	});

	pi.registerCommand("cd", {
		description: "Move this session (history kept) to another working directory",
		handler: async (args, ctx) => {
			const target = resolveTarget(ctx.cwd, args.trim());
			const continueTask = target === continueTarget;
			continueTarget = undefined;
			const blocked = checkTarget(ctx, target);
			if (blocked) {
				ctx.ui.notify(blocked, "error");
				return;
			}
			const sessionFile = sessionFileIn(target, ctx.sessionManager as SessionManager);
			const { cancelled } = await ctx.switchSession(sessionFile, {
				withSession: async (replaced) => {
					if (continueTask) await replaced.sendUserMessage(CONTINUE_MESSAGE);
				},
			});
			if (cancelled) fs.rmSync(sessionFile, { force: true });
		},
	});
}
