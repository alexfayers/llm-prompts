// Adds the fork tool, which runs a delegate on a copy of this session that shares its prompt cache. A writer works in a git worktree and lands its commits through the merge queue.
// Env: PI_CONTEXT_KEEP_FORKS (keep the seed and handshake files of finished forks), PI_HERDSMAN_MAILBOX and PI_CONTEXT_CHILD (set in a delegate, which cannot fork)
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { getAgentDir, type ExtensionAPI, type ExtensionContext, type SessionEntry } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { projectResult } from "../outcome-codes.ts";
import { createWorktree, land, type Event, type Landing, type Worktree } from "./merge.ts";
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

export type DelegateOptions = {
	role: Role;
	name: string;
	entries: SessionEntry[];
	message: string;
	signal?: AbortSignal;
	command?: string[];
	/** The worktree a writer works in. */
	worktree?: string;
	/** Runs after the first turn while the session is still open; `resume` prompts it again. */
	onTurn?: (turn: Turn, resume: (message: string) => Promise<Turn>) => Promise<void>;
};

/** Runs the role's session on a copy of the given entries with main's model, thinking level and directory, and returns its first turn. */
export async function runDelegate(pi: ExtensionAPI, ctx: ExtensionContext, { role, name, entries, message, signal, command, worktree, onTurn }: DelegateOptions): Promise<Turn> {
	if (!ctx.model) throw new Error("Cannot start a delegate without a model.");
	const files = path.join(getAgentDir(), "pi-context", randomUUID());
	const seed = path.join(files, "seed.jsonl");
	const handshake = path.join(files, "handshake.json");
	fs.mkdirSync(files, { recursive: true, mode: 0o700 });
	const header = { ...ctx.sessionManager.getHeader(), id: randomUUID() };
	fs.writeFileSync(seed, jsonl([header, ...entries]), { mode: 0o600 });
	fs.writeFileSync(handshake, JSON.stringify({ role: role.name, worktree }), { mode: 0o600 });
	const child = RpcChild.start({
		command,
		cwd: ctx.cwd,
		args: ["--mode", "rpc", "--session", seed, "--model", `${ctx.model.provider}/${ctx.model.id}`, "--thinking", pi.getThinkingLevel()],
		env: { ...process.env, PI_CONTEXT_CHILD: handshake },
		signal,
		onUi: relayDialog(name, ctx),
	});
	try {
		const turn = await child.prompt(`${role.card}\n\n${message}`);
		await onTurn?.(turn, (next) => child.prompt(next));
		return turn;
	} finally {
		await child.close();
		if (!process.env.PI_CONTEXT_KEEP_FORKS) fs.rmSync(files, { recursive: true });
	}
}

const WORKTREES = "worktrees";

function describeLanding(landing: Landing, tree: Worktree): string {
	if (landing.state === "escalated") return `escalated: ${landing.reason}\nworktree kept at ${tree.path} on branch ${tree.branch}`;
	return [landing.sha ? `landed ${landing.sha.slice(0, 9)}` : "nothing to land", landing.note].filter(Boolean).join("; ");
}

/** What a delegate's reply says about its work: done, or an outcome that stops the landing. */
function replyEvent(turn: Turn): Extract<Event, { type: "fork-done" | "fork-failed" | "fork-blocked" }> {
	const reason = turn.error ?? projectResult(turn.text);
	if (turn.error || /^OUTCOME failed /m.test(turn.text)) return { type: "fork-failed", reason };
	return /^OUTCOME blocked-on-user /m.test(turn.text) ? { type: "fork-blocked", reason } : { type: "fork-done" };
}

export function registerFork(pi: ExtensionAPI, command?: string[]) {
	pi.registerTool({
		name: "fork",
		label: "Fork",
		description:
			"Run a delegate on a copy of this session, so it knows everything you know and reuses the prompt cache. Give it one self-contained task. A reader (the default) only reads. A writer works in its own git worktree and its commits are rebased, tested and fast-forwarded onto the current branch. It blocks until the delegate replies with an OUTCOME line and the work has landed.",
		promptSnippet: "Run a read-only or worktree-writing delegate on a copy of this session and wait for its reply",
		parameters: Type.Object({
			task: Type.String({ description: "What the delegate should find out or check" }),
			role: Type.Optional(Type.Union([Type.Literal("reader"), Type.Literal("writer")], { description: "reader (default) reads only, writer commits in its own worktree" })),
			name: Type.Optional(Type.String({ pattern: "^[a-z0-9-]{1,24}$", description: "Short name for the delegate" })),
		}),
		async execute(toolCallId, params, signal, _onUpdate, ctx) {
			if (process.env.PI_HERDSMAN_MAILBOX || process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can fork.");
			if (!ctx.model) throw new Error("Cannot fork without a model.");
			const role: Role = ROLES[params.role ?? "reader"];
			const name = params.name ?? `fork-${randomUUID().slice(0, 6)}`;
			const tree = role.writes ? await createWorktree(ctx.cwd, path.join(getAgentDir(), "pi-context", WORKTREES), name) : undefined;
			const entries = seedEntries(ctx.sessionManager.getBranch(), toolCallId);
			const merged: { landing?: Landing } = {};
			const onTurn = tree && (async (turn: Turn, resume: (message: string) => Promise<Turn>) => {
				if (!turn.error) merged.landing = await land({ tree, signal, first: replyEvent(turn), resume: async (message) => replyEvent(await resume(message)) });
			});
			const message = `${tree ? `Your worktree: ${tree.path}\n` : ""}Task: ${params.task}`;
			const turn = await runDelegate(pi, ctx, { role, name, entries, message, signal, command, worktree: tree?.path, onTurn });
			if (turn.error) throw new Error(`fork ${name} failed: ${turn.error}${tree ? ` (worktree ${tree.path} kept)` : ""}`);
			const ref = `rc-fork-${name}-${toolCallId}`;
			pi.appendEntry("result-cap", { ref, text: turn.text });
			const cache = turn.firstUsage ? `cache ${turn.firstUsage.cacheRead}/${turn.firstUsage.cacheWrite}, ` : "";
			return {
				content: [{ type: "text", text: `${projectResult(turn.text)}\n[fork ${name}: ${cache}ref ${ref}]${merged.landing && tree ? `\n[merge: ${describeLanding(merged.landing, tree)}]` : ""}` }],
				details: { name, role: role.name, outcome: /^OUTCOME (\S+)/m.exec(turn.text)?.[1], usage: turn.usage, firstUsage: turn.firstUsage, merge: merged.landing },
			};
		},
	});
}
