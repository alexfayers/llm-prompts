// Appends one JSON line per tool call (session, role, tool, nested, skill path) to usage-ledger.jsonl in the agent dir.
import { appendFile } from "node:fs/promises";
import { join } from "node:path";
import { getAgentDir, type ExtensionAPI, type ExtensionContext, type ToolCallEvent } from "@earendil-works/pi-coding-agent";

const SKILL_FILE = "/SKILL.md";

export function ledgerRecord(event: ToolCallEvent, ctx: Pick<ExtensionContext, "sessionManager">) {
	const path = event.toolName === "read" ? event.input.path : undefined;
	return {
		ts: Date.now(),
		session: ctx.sessionManager.getSessionId(),
		role: process.env.PI_HERDSMAN_AGENT_DEFINITION ?? "main",
		tool: event.toolName,
		nested: event.parentToolCallId !== undefined,
		...(typeof path === "string" && path.endsWith(SKILL_FILE) ? { skillPath: path } : {}),
	};
}

export default function (pi: ExtensionAPI) {
	let warned = false;
	pi.on("tool_call", (event, ctx) => {
		void appendFile(join(getAgentDir(), "usage-ledger.jsonl"), `${JSON.stringify(ledgerRecord(event, ctx))}\n`).catch((error) => {
			if (warned) return;
			warned = true;
			try {
				if (ctx.hasUI) ctx.ui.notify(`usage-ledger: cannot write (${error instanceof Error ? error.message : error})`, "warning");
			} catch {
				return;
			}
		});
	});
}
