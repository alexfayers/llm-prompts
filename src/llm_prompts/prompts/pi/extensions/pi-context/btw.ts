// Answers `//btw <question>` on a read-only copy of the session and stores the answer outside the model context.
import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { Box, Text } from "@earendil-works/pi-tui";
import { runDelegate } from "./fork.ts";
import { ROLES } from "./roles.ts";

const BTW = /^\/\/btw\s+([\s\S]+)/;

/** The entries up to the first assistant message whose tool calls have no result yet: a point the model could continue from. */
export function settledEntries(branch: SessionEntry[]): SessionEntry[] {
	const answered = new Set(branch.flatMap((entry) => (entry.type === "message" && entry.message.role === "toolResult" ? [entry.message.toolCallId] : [])));
	const open = branch.findIndex(
		(entry) => entry.type === "message" && entry.message.role === "assistant" && entry.message.content.some((block) => block.type === "toolCall" && !answered.has(block.id)),
	);
	return open < 0 ? branch : branch.slice(0, open);
}

async function answer(pi: ExtensionAPI, ctx: ExtensionContext, question: string, command?: string[]) {
	try {
		const turn = await runDelegate(pi, ctx, { role: ROLES.btw, name: `btw-${randomUUID().slice(0, 6)}`, entries: settledEntries(ctx.sessionManager.getBranch()), message: `Question: ${question}`, command });
		if (turn.error) throw new Error(turn.error);
		pi.appendEntry("pi-context-btw", { q: question, a: turn.text });
	} catch (error) {
		ctx.ui.notify(`btw failed: ${error instanceof Error ? error.message : String(error)}`, "warning");
	}
}

export function registerBtw(pi: ExtensionAPI, command?: string[]) {
	pi.registerEntryRenderer<{ q: string; a: string }>("pi-context-btw", (entry, _options, theme) => {
		const box = new Box(1, 1, (text) => theme.bg("customMessageBg", text));
		box.addChild(new Text(`${theme.bold(`btw: ${entry.data?.q}`)}\n${entry.data?.a}`));
		return box;
	});
	pi.on("input", (event, ctx) => {
		const question = BTW.exec(event.text.trim())?.[1];
		if (!question || event.source === "extension" || !ctx.hasUI || ctx.model === undefined || process.env.PI_HERDSMAN_MAILBOX || process.env.PI_CONTEXT_CHILD) return undefined;
		ctx.ui.notify("btw: asking a read-only copy of this session", "info");
		answer(pi, ctx, question, command).catch(() => undefined);
		return { action: "handled" as const };
	});
}
