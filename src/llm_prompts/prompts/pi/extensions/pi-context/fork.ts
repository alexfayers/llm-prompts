// Adds the fork tool, which runs a delegate on a copy of this session that shares its prompt cache, or a cold worker on a cheaper model. A writer works in a git worktree and lands its commits through the merge queue.
// Env: PI_CONTEXT_KEEP_FORKS (keep the seed, session and handshake files of finished forks), PI_CONTEXT_MCP_PROXY (1: a fork uses main's MCP servers), PI_HERDSMAN_MAILBOX and PI_CONTEXT_CHILD (set in a delegate, which cannot fork), PI_CONTEXT_ROLE and PI_CONTEXT_RUN_ID (set for a delegate)
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { getAgentDir, type ExtensionAPI, type ExtensionContext, type SessionEntry } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { parseOutcome, projectResult } from "../outcome-codes.ts";
import { describeMain, lastPrefixHash, mcpProxyEnabled, serveBridge, type BridgeOptions } from "./bridge.ts";
import { createWorktree, land, type Event, type Landing, type Worktree } from "./merge.ts";
import { coldCard, ROLES, type Role } from "./roles.ts";
import { registryOf, type RunState } from "./registry.ts";
import { RpcChild, type Turn, type UiAnswer, type UiRequest } from "./runner.ts";

const holdsCall = (entry: SessionEntry, toolCallId: string) =>
	entry.type === "message" && entry.message.role === "assistant" && entry.message.content.some((block) => block.type === "toolCall" && block.id === toolCallId);

/** The entries before the assistant message holding the call: the part of the session the last request cached. */
export function seedEntries(branch: SessionEntry[], toolCallId: string): SessionEntry[] {
	const at = branch.findIndex((entry) => holdsCall(entry, toolCallId));
	return at < 0 ? branch : branch.slice(0, at);
}

export type ColdOptions = { model: string; sessionDir: string; cardFile: string; skillsDir: string };

/** The arguments of a cold worker: a fresh session on its own model with only the role's skills, the role card in its system prompt and no MCP servers of its own. */
export function coldArgs(role: Role, { model, sessionDir, cardFile, skillsDir }: ColdOptions): string[] {
	const skills = role.skills.flatMap((skill) => ["--skill", path.join(skillsDir, skill)]);
	return ["--mode", "rpc", "--session-dir", sessionDir, "--model", model, "--no-skills", ...skills, "--append-system-prompt", cardFile, "--no-mcp"];
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

export const newRunId = () => randomUUID().slice(0, 8);

export type DelegateOptions = {
	role: Role;
	name: string;
	entries: SessionEntry[];
	message: string;
	signal?: AbortSignal;
	command?: string[];
	/** Names the run in the delegate's environment (PI_CONTEXT_RUN_ID). */
	runId?: string;
	/** Runs the delegate as a cold worker on this model: an empty session, and only the role's skills and MCP tools. */
	model?: string;
	/** Runs the delegate's MCP calls in main, so the delegate starts no MCP servers of its own. */
	mcp?: BridgeOptions["execute"];
	/** The worktree a writer works in. */
	worktree?: string;
	/** Runs after the first turn while the session is still open; `resume` prompts it again. */
	onTurn?: (turn: Turn, resume: (message: string) => Promise<Turn>) => Promise<void>;
};

/** Runs the role's session on a copy of the given entries with main's model, thinking level and directory, or as a cold worker with `model`, and returns its first turn. */
export async function runDelegate(pi: ExtensionAPI, ctx: ExtensionContext, { role, name, entries, message, signal, command, runId = newRunId(), model, mcp, worktree, onTurn }: DelegateOptions): Promise<Turn & { prefix?: "match" | "mismatch" }> {
	if (!ctx.model) throw new Error("Cannot start a delegate without a model.");
	const agentDir = getAgentDir();
	const files = path.join(agentDir, "pi-context", randomUUID());
	const seed = path.join(files, "seed.jsonl");
	const handshake = path.join(files, "handshake.json");
	const cardFile = path.join(files, "card.md");
	fs.mkdirSync(files, { recursive: true, mode: 0o700 });
	let prefix: "match" | "mismatch" | undefined;
	const onPrefix = model ? undefined : (hash: string) => void (prefix = hash === lastPrefixHash() ? "match" : "mismatch");
	const bridge = mcp && (await serveBridge(files, { role, execute: mcp, onPrefix }));
	fs.writeFileSync(handshake, JSON.stringify({ role: role.name, worktree, bridge: bridge && { ...describeMain(pi, ctx, model ? role : undefined), socket: bridge.socket } }), { mode: 0o600 });
	if (model) fs.writeFileSync(cardFile, coldCard(role), { mode: 0o600 });
	else fs.writeFileSync(seed, jsonl([{ ...ctx.sessionManager.getHeader(), id: randomUUID() }, ...entries]), { mode: 0o600 });
	const child = RpcChild.start({
		command,
		cwd: (model && worktree) || ctx.cwd,
		args: model
			? coldArgs(role, { model, sessionDir: path.join(files, "session"), cardFile, skillsDir: path.join(agentDir, "skills") })
			: ["--mode", "rpc", "--session", seed, "--model", `${ctx.model.provider}/${ctx.model.id}`, "--thinking", pi.getThinkingLevel(), ...(bridge ? ["--no-mcp"] : [])],
		env: { ...process.env, PI_CONTEXT_CHILD: handshake, PI_CONTEXT_ROLE: role.name, PI_CONTEXT_RUN_ID: runId },
		signal,
		onUi: relayDialog(name, ctx),
	});
	try {
		const turn = await child.prompt(model ? message : `${role.card}\n\n${message}`);
		await onTurn?.(turn, (next) => child.prompt(next));
		return { ...turn, prefix };
	} finally {
		await child.close();
		await bridge?.close();
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
	const code = parseOutcome(turn.text)?.code;
	if (turn.error || code === "failed") return { type: "fork-failed", reason };
	return code === "blocked-on-user" ? { type: "fork-blocked", reason } : { type: "fork-done" };
}

function finalState(code: string | undefined, landing: Landing | undefined): RunState {
	if (code === "failed") return "failed";
	if (code === "blocked-on-user" || landing?.state === "escalated") return "blocked";
	return code === "found-it" ? "found-it" : "done";
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
			model: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][\\w./:@-]*$", description: "Run as a cold worker on this cheaper model (provider/id, optionally :thinking). It starts with an empty session, so the task must be self-contained" })),
		}),
		async execute(toolCallId, params, signal, _onUpdate, ctx) {
			if (process.env.PI_HERDSMAN_MAILBOX || process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can fork.");
			if (!ctx.model) throw new Error("Cannot fork without a model.");
			const role: Role = ROLES[params.role ?? "reader"];
			const name = params.name ?? `fork-${randomUUID().slice(0, 6)}`;
			const tree = role.writes ? await createWorktree(ctx.cwd, path.join(getAgentDir(), "pi-context", WORKTREES), name) : undefined;
			const entries = seedEntries(ctx.sessionManager.getBranch(), toolCallId);
			const merged: { landing?: Landing } = {};
			const runId = newRunId();
			const registry = registryOf();
			registry.start({ id: runId, name, role: role.name, background: false, state: "running", task: params.task, worktree: tree?.path, branch: tree?.branch, startedAt: Date.now() });
			const onTurn = tree && (async (turn: Turn, resume: (message: string) => Promise<Turn>) => {
				if (turn.error) return;
				registry.update(runId, { state: "landing" });
				merged.landing = await land({ tree, signal, first: replyEvent(turn), resume: async (message) => replyEvent(await resume(message)) });
			});
			const message = `${tree ? `Your worktree: ${tree.path}\n` : ""}Task: ${params.task}`;
			const mcp = params.model || mcpProxyEnabled() ? async (tool: string, args: unknown) => {
				const { result, isError } = await ctx.executeTool(tool, args, { signal });
				return { content: result.content, details: result.details, structuredContent: result.structuredContent, isError };
			} : undefined;
			let turn: Awaited<ReturnType<typeof runDelegate>>;
			try {
				turn = await runDelegate(pi, ctx, { role, name, entries, message, signal, command, runId, model: params.model, mcp, worktree: tree?.path, onTurn });
			} catch (error) {
				registry.update(runId, { state: "failed", endedAt: Date.now() });
				throw error;
			}
			if (turn.error) {
				registry.update(runId, { state: "failed", endedAt: Date.now() });
				throw new Error(`fork ${name} failed: ${turn.error}${tree ? ` (worktree ${tree.path} kept)` : ""}`);
			}
			const ref = `rc-fork-${name}-${toolCallId}`;
			const outcome = parseOutcome(turn.text)?.code;
			registry.update(runId, { state: finalState(outcome, merged.landing), outcome, ref, endedAt: Date.now() });
			pi.appendEntry("result-cap", { ref, text: turn.text });
			const cache = turn.firstUsage ? `cache ${turn.firstUsage.cacheRead}/${turn.firstUsage.cacheWrite}, ` : "";
			return {
				content: [{ type: "text", text: `${projectResult(turn.text)}\n[fork ${name}: ${cache}ref ${ref}]${merged.landing && tree ? `\n[merge: ${describeLanding(merged.landing, tree)}]` : ""}` }],
				details: { name, role: role.name, outcome, usage: turn.usage, firstUsage: turn.firstUsage, prefix: turn.prefix, merge: merged.landing },
			};
		},
	});
}
