// Adds the fork tool, which runs a read-only delegate on a copy of this session that shares its prompt cache.
// Env: PI_CONTEXT_KEEP_FORKS (keep the seed and handshake files of finished forks), PI_HERDSMAN_MAILBOX and PI_CONTEXT_CHILD (set in a delegate, which cannot fork)
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { getAgentDir, type ExtensionAPI, type ExtensionContext, type SessionEntry } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { projectResult } from "../outcome-codes.ts";
import { ROLES, type Role } from "./roles.ts";
import { RpcChild, type Turn, type UiAnswer, type UiRequest } from "./runner.ts";

const holdsCall = (entry: SessionEntry, toolCallId: string) =>
	entry.type === "message" && entry.message.role === "assistant" && entry.message.content.some((block) => block.type === "toolCall" && block.id === toolCallId);

/** The entries before the assistant message holding the call: the part of the session the last request cached. */
export function seedEntries(branch: SessionEntry[], toolCallId: string): SessionEntry[] {
	const at = branch.findIndex((entry) => holdsCall(entry, toolCallId));
	return at < 0 ? branch : branch.slice(0, at);
}

const jsonl = (records: unknown[]) => records.map((record) => `${JSON.stringify(record)}\n`).join("");

function relayDialog(name: string, ctx: ExtensionContext) {
	return async (request: UiRequest): Promise<UiAnswer | undefined> => {
		if (!ctx.hasUI) return undefined;
		const title = `[fork ${name}] ${request.title}`;
		if (request.method === "confirm") return { confirmed: await ctx.ui.confirm(title, String(request.message ?? "")) };
		if (request.method === "select") return { value: await ctx.ui.select(title, request.options as string[]) };
		if (request.method === "input") return { value: await ctx.ui.input(title, request.placeholder as string | undefined) };
		return undefined;
	};
}

export type DelegateOptions = { role: Role; name: string; entries: SessionEntry[]; message: string; signal?: AbortSignal; command?: string[] };

/** Runs the role's session on a copy of the given entries with main's model, thinking level and directory, and returns its turn. */
export async function runDelegate(pi: ExtensionAPI, ctx: ExtensionContext, { role, name, entries, message, signal, command }: DelegateOptions): Promise<Turn> {
	if (!ctx.model) throw new Error("Cannot start a delegate without a model.");
	const files = path.join(getAgentDir(), "pi-context", randomUUID());
	const seed = path.join(files, "seed.jsonl");
	const handshake = path.join(files, "handshake.json");
	fs.mkdirSync(files, { recursive: true, mode: 0o700 });
	const header = { ...ctx.sessionManager.getHeader(), id: randomUUID() };
	fs.writeFileSync(seed, jsonl([header, ...entries]), { mode: 0o600 });
	fs.writeFileSync(handshake, JSON.stringify({ role: role.name }), { mode: 0o600 });
	const child = RpcChild.start({
		command,
		cwd: ctx.cwd,
		args: ["--mode", "rpc", "--session", seed, "--model", `${ctx.model.provider}/${ctx.model.id}`, "--thinking", pi.getThinkingLevel()],
		env: { ...process.env, PI_CONTEXT_CHILD: handshake },
		signal,
		onUi: relayDialog(name, ctx),
	});
	try {
		return await child.prompt(`${role.card}\n\n${message}`);
	} finally {
		await child.close();
		if (!process.env.PI_CONTEXT_KEEP_FORKS) fs.rmSync(files, { recursive: true });
	}
}

export function registerFork(pi: ExtensionAPI, command?: string[]) {
	const role = ROLES.reader;
	pi.registerTool({
		name: "fork",
		label: "Fork",
		description:
			"Run a read-only delegate on a copy of this session, so it knows everything you know and reuses the prompt cache. Give it one self-contained task. It blocks until the delegate replies with an OUTCOME line.",
		promptSnippet: "Run a read-only delegate on a copy of this session and wait for its reply",
		parameters: Type.Object({
			task: Type.String({ description: "What the delegate should find out or check" }),
			name: Type.Optional(Type.String({ pattern: "^[a-z0-9-]{1,24}$", description: "Short name for the delegate" })),
		}),
		async execute(toolCallId, params, signal, _onUpdate, ctx) {
			if (process.env.PI_HERDSMAN_MAILBOX || process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can fork.");
			if (!ctx.model) throw new Error("Cannot fork without a model.");
			const name = params.name ?? `fork-${randomUUID().slice(0, 6)}`;
			const entries = seedEntries(ctx.sessionManager.getBranch(), toolCallId);
			const turn = await runDelegate(pi, ctx, { role, name, entries, message: `Task: ${params.task}`, signal, command });
			if (turn.error) throw new Error(`fork ${name} failed: ${turn.error}`);
			const ref = `rc-fork-${name}-${toolCallId}`;
			pi.appendEntry("result-cap", { ref, text: turn.text });
			const cache = turn.firstUsage ? `cache ${turn.firstUsage.cacheRead}/${turn.firstUsage.cacheWrite}, ` : "";
			return {
				content: [{ type: "text", text: `${projectResult(turn.text)}\n[fork ${name}: ${cache}ref ${ref}]` }],
				details: { name, role: role.name, outcome: /^OUTCOME (\S+)/m.exec(turn.text)?.[1], usage: turn.usage, firstUsage: turn.firstUsage },
			};
		},
	});
}
