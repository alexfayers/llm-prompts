// Raises Herdr notifications when a turn finishes or pi needs input, on the /notify command and on the notify tool.
import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const HERDR_TIMEOUT_MS = 5000;
const DEFAULT_TITLE = "pi";
const TITLE_SEPARATOR = " | ";
const USAGE = "Usage: /notify <message> [| <title>]";
const SHOWN = "Notification shown";
const NOT_SHOWN = "Notification not shown: not in a Herdr pane or Herdr declined it";

const SOUNDS = ["none", "done", "request"] as const;
const PARAMETERS = Type.Object({
	title: Type.String({ description: "Short notification title." }),
	body: Type.Optional(Type.String({ description: "Longer notification text." })),
	sound: Type.Optional(StringEnum(SOUNDS, { description: "`done` for finished work, `request` when you need the user, `none` for silent." })),
});

export type Notification = { title: string; body?: string; sound?: (typeof SOUNDS)[number] };

export function inHerdrPane(env: Record<string, string | undefined>): boolean {
	return env.HERDR_ENV === "1" || Boolean(env.HERDR_PANE_ID) || Boolean(env.HERDR_SOCKET_PATH);
}

export function autoEnabled(env: Record<string, string | undefined>): boolean {
	return !env.PI_SUBAGENT_CHILD && !env.PI_HERDSMAN_MAILBOX && env.PI_NOTIFY_AUTO !== "0";
}

export async function notify({ title, body, sound }: Notification): Promise<boolean> {
	if (!inHerdrPane(process.env)) return false;
	const args = ["notification", "show", title];
	if (body) args.push("--body", body);
	if (sound) args.push("--sound", sound);
	try {
		const { stdout } = await execFileAsync("herdr", args, { timeout: HERDR_TIMEOUT_MS });
		return (JSON.parse(stdout) as { result?: { shown?: boolean } }).result?.shown === true;
	} catch {
		return false;
	}
}

async function notifyAutomatically(notification: Notification): Promise<void> {
	if (autoEnabled(process.env)) await notify(notification);
}

function tell(ctx: ExtensionContext, message: string, level: "info" | "warning"): void {
	if (ctx.hasUI) ctx.ui.notify(message, level);
}

export function parseCommand(args: string): Notification | undefined {
	const text = args.trim();
	if (!text) return undefined;
	const split = text.indexOf(TITLE_SEPARATOR);
	if (split < 0) return { title: DEFAULT_TITLE, body: text };
	return { title: text.slice(split + TITLE_SEPARATOR.length).trim() || DEFAULT_TITLE, body: text.slice(0, split).trim() };
}

export default function (pi: ExtensionAPI) {
	pi.on("agent_settled", async (event, ctx) => {
		if (!event.aborted) await notifyAutomatically({ title: "pi is done", body: path.basename(ctx.cwd), sound: "done" });
	});
	pi.on("ui_prompt_start", async (event) => {
		if (event.kind === "custom") return;
		await notifyAutomatically({ title: "pi needs input", body: event.title, sound: "request" });
	});
	pi.registerCommand("notify", {
		description: "Raise a Herdr notification: /notify <message> [| <title>]",
		handler: async (args, ctx) => {
			const notification = parseCommand(args);
			if (!notification) return tell(ctx, USAGE, "warning");
			const shown = await notify(notification);
			tell(ctx, shown ? SHOWN : NOT_SHOWN, shown ? "info" : "warning");
		},
	});
	pi.registerTool({
		name: "notify",
		label: "Notify",
		description: "Raise a Herdr notification so the user notices, e.g. when you are blocked on them or a long task finished. Does nothing outside Herdr. Use sparingly.",
		promptSnippet: "Raise a Herdr notification for the user",
		parameters: PARAMETERS,
		async execute(_toolCallId, params) {
			const shown = await notify(params);
			return { content: [{ type: "text", text: `${shown ? SHOWN : NOT_SHOWN}.` }], details: { shown } };
		},
	});
}
