// Adds the fork tool, which runs a delegate on a copy of this session that shares its prompt cache, or a cold worker on a cheaper model. A writer works in a git worktree and lands its commits through the merge queue.
// Env: PI_CONTEXT_KEEP_FORKS (keep the seed, session and handshake files of finished forks), PI_CONTEXT_MCP_PROXY (1: a fork uses main's MCP servers), PI_HERDSMAN_MAILBOX and PI_CONTEXT_CHILD (set in a delegate, which cannot fork), PI_CONTEXT_ROLE and PI_CONTEXT_RUN_ID (set for a delegate)
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { getAgentDir, type ExtensionAPI, type ExtensionContext, type ExtensionToolContext, type SessionEntry } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { parseOutcome, projectResult } from "../outcome-codes.ts";
import { Background } from "./background.ts";
import { describeMain, lastPrefixHash, mcpProxyEnabled, PREFIX_FILE, serveBridge, type BridgeOptions } from "./bridge.ts";
import { createWorktree, dropIfClean, gitOut, land, restoreWorktree, type Event, type Landing, type Worktree } from "./merge.ts";
import { coldCard, expandHome, readHandshake, ROLES, type Role } from "./roles.ts";
import { isLive, registryOf, type Run, type RunState } from "./registry.ts";
import { RpcChild, type Turn, type UiAnswer, type UiRequest } from "./runner.ts";
import { pinForkAsks } from "./wake.ts";

const holdsCall = (entry: SessionEntry, toolCallId: string) =>
	entry.type === "message" && entry.message.role === "assistant" && entry.message.content.some((block) => block.type === "toolCall" && block.id === toolCallId);

/** The entries before the assistant message holding the call: the part of the session the last request cached. */
export function seedEntries(branch: SessionEntry[], toolCallId: string): SessionEntry[] {
	const at = branch.findIndex((entry) => holdsCall(entry, toolCallId.split("/")[0]));
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
	entries?: SessionEntry[];
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
	/** The main checkout the writer's worktree belongs to. */
	repo?: string;
	/** The directory the delegate works in instead of main's. */
	cwd?: string;
	/** The run's file directory. A new one is made when it is not given. */
	files?: string;
	/** Continue the session already in `files` instead of seeding a new one. */
	resume?: boolean;
	/** Keeps the run's files when the delegate ends, so a lost run can resume. */
	keep?: () => boolean;
	/** Receives the child once it has started. */
	onChild?: (child: RpcChild) => void;
	/** Runs after the first turn while the session is still open; `resume` prompts it again. */
	onTurn?: (turn: Turn, resume: (message: string) => Promise<Turn>) => Promise<void>;
};

/** Runs the role's session on a copy of the given entries with main's model, thinking level and directory, or as a cold worker with `model`, and returns its first turn. */
export async function runDelegate(pi: ExtensionAPI, ctx: ExtensionContext, { role, name, entries = [], message, signal, command, runId = newRunId(), model, mcp, worktree, repo, cwd, files = path.join(getAgentDir(), "pi-context", randomUUID()), resume, keep, onChild, onTurn }: DelegateOptions): Promise<Turn & { prefix?: "match" | "mismatch" }> {
	if (!ctx.model) throw new Error("Cannot start a delegate without a model.");
	if (resume && model) throw new Error("A cold worker cannot resume.");
	const agentDir = getAgentDir();
	registryOf().update(runId, { files, model });
	const seed = path.join(files, "seed.jsonl");
	const handshake = path.join(files, "handshake.json");
	const cardFile = path.join(files, "card.md");
	const sessionDir = path.join(files, "session");
	let bridge: Awaited<ReturnType<typeof serveBridge>> | undefined;
	let child: RpcChild | undefined;
	try {
		fs.mkdirSync(files, { recursive: true, mode: 0o700 });
		let prefix: "match" | "mismatch" | undefined;
		const onPrefix = model ? undefined : (hash: string) => void (prefix = hash === lastPrefixHash() ? "match" : "mismatch");
		bridge = mcp && (await serveBridge(files, { role, execute: mcp, onPrefix }));
		const inherited = model ? undefined : resume ? readHandshake(handshake)?.inherited : entries.at(-1)?.id;
		fs.writeFileSync(handshake, JSON.stringify({ role: role.name, worktree, repo, inherited, bridge: bridge && { ...describeMain(pi, ctx, model ? role : undefined), socket: bridge.socket } }), { mode: 0o600 });
		if (model) fs.writeFileSync(cardFile, coldCard(role), { mode: 0o600 });
		else if (!resume) fs.writeFileSync(seed, jsonl([{ ...ctx.sessionManager.getHeader(), id: randomUUID(), ...(cwd && { cwd }) }, ...entries]), { mode: 0o600 });
		child = RpcChild.start({
			command,
			cwd: (model && worktree) || cwd || ctx.cwd,
			args: model
				? coldArgs(role, { model, sessionDir, cardFile, skillsDir: path.join(agentDir, "skills") })
				: ["--mode", "rpc", "--session", seed, "--model", `${ctx.model.provider}/${ctx.model.id}`, "--thinking", pi.getThinkingLevel(), ...(bridge ? ["--no-mcp"] : [])],
			env: { ...process.env, PI_CONTEXT_CHILD: handshake, PI_CONTEXT_ROLE: role.name, PI_CONTEXT_RUN_ID: runId },
			signal,
			onUi: relayDialog(name, ctx),
		});
		onChild?.(child);
		const turn = await child.prompt(model || resume ? message : `${role.card}\n\n${message}`);
		const reported = !model && !bridge && readText(path.join(files, PREFIX_FILE));
		if (reported) prefix = reported === lastPrefixHash() ? "match" : "mismatch";
		await onTurn?.(turn, (next) => child!.prompt(next));
		return { ...turn, prefix };
	} finally {
		await child?.close();
		await bridge?.close();
		if (!process.env.PI_CONTEXT_KEEP_FORKS && !keep?.()) fs.rmSync(files, { recursive: true, force: true });
	}
}

const WORKTREES = "worktrees";

/** The toplevel of the git checkout at `target`, with `~` expanded and a relative path taken from `cwd`. */
async function checkoutOf(cwd: string, target: string): Promise<string> {
	const dir = path.resolve(cwd, expandHome(target));
	try {
		return await gitOut(dir, "rev-parse", "--show-toplevel");
	} catch {
		throw new Error(`target ${target} is not a git checkout`);
	}
}

const sameDir = (a: string, b: string) => fs.realpathSync(a) === fs.realpathSync(b);

/** Whether a lost run's session is still there to continue. A cold worker's is not kept. */
export const canResume = (run: Run): boolean => run.state === "lost" && run.background && !run.model && Boolean(run.files && fs.existsSync(path.join(run.files, "seed.jsonl")));

const readText = (file: string) => {
	try {
		return fs.readFileSync(file, "utf8");
	} catch {
		return undefined;
	}
};

function describeLanding(landing: Landing, tree: Worktree): string {
	if (landing.state === "escalated") return `escalated: ${landing.reason}\n${landing.removed ? "worktree removed: clean" : `worktree kept at ${tree.path} on branch ${tree.branch}`}`;
	return [landing.sha ? `landed ${landing.sha.slice(0, 9)}` : "nothing to land", landing.note].filter(Boolean).join("; ");
}

/** Removes a clean worktree of a fork that ended without landing, and says what happened to it. */
const treeNote = async (tree?: Worktree) => (!tree ? "" : (await dropIfClean(tree)) ? " (worktree removed: clean)" : ` (worktree ${tree.path} kept)`);

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

/** The run fields a finished delegate's reply decides. */
function endOf(ref: string, turn: Turn, landing: Landing | undefined): Pick<Run, "state" | "outcome" | "notify" | "ref"> {
	const parsed = parseOutcome(turn.text);
	if (turn.error) return { state: "failed", ref };
	return { state: finalState(parsed?.code, landing), outcome: parsed?.code, notify: parsed?.notify, ref };
}

function report(ctx: ExtensionContext, error: unknown) {
	const message = `fork: ${error instanceof Error ? error.message : String(error)}`;
	try {
		if (ctx.hasUI) ctx.ui.notify(message, "error");
		else process.stderr.write(`${message}\n`);
	} catch {
		process.stderr.write(`${message}\n`);
	}
}

export function registerFork(pi: ExtensionAPI, command?: string[], background = new Background(pi)) {
	const registry = registryOf();

	/** Starts the delegate of a registered run. A background run reports its end to `background`. */
	function startRun(ctx: ExtensionToolContext, run: { id: string; name: string; ref: string; role: Role; tree?: Worktree; target?: string; model?: string; files: string; background: boolean; signal?: AbortSignal }, delegate: Pick<DelegateOptions, "entries" | "message" | "resume">) {
		const { id: runId, name, ref, tree } = run;
		const merged: { landing?: Landing } = {};
		const runSignal = run.background ? background.track(runId) : run.signal;
		const onTurn = tree && (async (turn: Turn, resume: (message: string) => Promise<Turn>) => {
			if (turn.error) return;
			registry.update(runId, { state: "landing" });
			merged.landing = await land({ tree, signal: runSignal, first: replyEvent(turn), resume: async (message) => replyEvent(await resume(message)) });
		});
		const mcp = run.model || mcpProxyEnabled() ? async (tool: string, args: unknown) => {
			const { result, isError } = await ctx.executeTool(tool, args, { signal: runSignal });
			return { content: result.content, details: result.details, structuredContent: result.structuredContent, isError };
		} : undefined;
		const keep = () => registry.get(runId)?.state === "lost";
		const running = runDelegate(pi, ctx, { role: run.role, name, ...delegate, signal: runSignal, command, runId, model: run.model, mcp, worktree: tree?.path, repo: tree?.repo, cwd: run.target, files: run.files, keep, onChild: run.background ? (child) => background.attach(runId, child) : undefined, onTurn });
		if (run.background) {
			const onEnd = async (turn: Turn) => {
				const current = registry.get(runId);
				if (!current || !isLive(current)) return;
				const end = endOf(ref, turn, merged.landing);
				const text = turn.error ?? turn.text;
				const note = merged.landing && tree ? `[merge: ${describeLanding(merged.landing, tree)}]` : tree && (await dropIfClean(tree)) ? "[merge: worktree removed: clean]" : undefined;
				background.finish(ctx, runId, end, text, note);
				pi.appendEntry("result-cap", { ref: end.ref, text });
			};
			const onFail = async (error: unknown) => {
				if (registry.get(runId)?.state === "lost") return;
				const removed = tree && (await dropIfClean(tree));
				background.finish(ctx, runId, { state: "failed" }, error instanceof Error ? error.message : String(error), removed ? "[merge: worktree removed: clean]" : undefined);
			};
			void running.then(onEnd, onFail).catch((error) => report(ctx, error));
		}
		return { running, merged };
	}

	pi.registerTool({
		name: "fork",
		label: "Fork",
		description:
			"Run a delegate on a copy of this session, so it knows everything you know and reuses the prompt cache. Give it one self-contained task. A reader (the default) only reads. A writer works in its own git worktree and its commits are rebased, tested and fast-forwarded onto the current branch. target points either role at another git checkout. It blocks until the delegate replies with an OUTCOME line and the work has landed. With background true it returns at once and the result arrives as a message when the delegate finishes.",
		promptSnippet: "Run a read-only or worktree-writing delegate on a copy of this session and wait for its reply",
		parameters: Type.Object({
			task: Type.String({ description: "What the delegate should find out or check" }),
			role: Type.Optional(Type.Union([Type.Literal("reader"), Type.Literal("writer")], { description: "reader (default) reads only, writer commits in its own worktree" })),
			name: Type.Optional(Type.String({ pattern: "^[a-z0-9-]{1,24}$", description: "Short name for the delegate" })),
			background: Type.Optional(Type.Boolean({ description: "Return at once and receive the result later as a message, so you can keep working" })),
			target: Type.Optional(Type.String({ description: "Path of another git checkout or worktree to read or land in, instead of this session's" })),
			model: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][\\w./:@-]*$", description: "Run as a cold worker on this cheaper model (provider/id, optionally :thinking). It starts with an empty session, so the task must be self-contained" })),
		}),
		async execute(toolCallId, params, signal, _onUpdate, ctx) {
			if (process.env.PI_HERDSMAN_MAILBOX || process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can fork.");
			if (!ctx.model) throw new Error("Cannot fork without a model.");
			const role: Role = ROLES[params.role ?? "reader"];
			const name = params.name ?? `fork-${randomUUID().slice(0, 6)}`;
			const checkout = params.target === undefined ? undefined : await checkoutOf(ctx.cwd, params.target);
			const target = checkout && !sameDir(checkout, ctx.cwd) ? checkout : undefined;
			const tree = role.writes ? await createWorktree(checkout ?? ctx.cwd, path.join(getAgentDir(), "pi-context", WORKTREES), name) : undefined;
			const entries = seedEntries(ctx.sessionManager.getBranch(), toolCallId);
			const runId = newRunId();
			const ref = `rc-fork-${name}-${toolCallId}`;
			const files = path.join(getAgentDir(), "pi-context", randomUUID());
			registry.start({ id: runId, name, role: role.name, background: Boolean(params.background), state: "running", task: params.task, worktree: tree?.path, branch: tree?.branch, tree, target, startedAt: Date.now() });
			const message = `${tree ? `Your worktree: ${tree.path}\n` : ""}Task: ${params.task}`;
			const { running, merged } = startRun(ctx, { id: runId, name, ref, role, tree, target, model: params.model, files, background: Boolean(params.background), signal }, { entries, message });
			if (params.background) {
				return { content: [{ type: "text", text: `started fork ${name} (background)` }], details: { name, runId, background: true } };
			}
			let turn: Awaited<typeof running>;
			try {
				turn = await running;
			} catch (error) {
				registry.update(runId, { state: "failed", endedAt: Date.now() });
				throw new Error(`fork ${name} failed: ${error instanceof Error ? error.message : String(error)}${await treeNote(tree)}`, { cause: error });
			}
			if (turn.error) {
				registry.update(runId, { state: "failed", endedAt: Date.now() });
				throw new Error(`fork ${name} failed: ${turn.error}${await treeNote(tree)}`);
			}
			const end = endOf(ref, turn, merged.landing);
			registry.update(runId, { ...end, endedAt: Date.now() });
			pi.appendEntry("result-cap", { ref: end.ref, text: turn.text });
			pinForkAsks(pi, ctx, { id: runId, name }, turn.text);
			const cache = `${turn.prefix === "mismatch" ? "prefix mismatch, " : ""}${turn.firstUsage ? `cache ${turn.firstUsage.cacheRead}/${turn.firstUsage.cacheWrite}, ` : ""}`;
			return {
				content: [{ type: "text", text: `${projectResult(turn.text)}\n[fork ${name}: ${cache}ref ${end.ref}]${merged.landing && tree ? `\n[merge: ${describeLanding(merged.landing, tree)}]` : ""}` }],
				details: { name, role: role.name, outcome: end.outcome, usage: turn.usage, firstUsage: turn.firstUsage, prefix: turn.prefix, merge: merged.landing },
			};
		},
	});
	pi.registerTool({
		name: "fork_cancel",
		label: "Fork cancel",
		description: "Stop a live background fork by name. A writer's worktree stays where it is.",
		promptSnippet: "Stop a live background fork",
		parameters: Type.Object({ name: Type.String({ description: "Name of the background fork" }) }),
		async execute(_toolCallId, params) {
			if (process.env.PI_HERDSMAN_MAILBOX || process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can fork.");
			const run = background.cancel(params.name);
			if (!run) throw new Error(`no live background fork ${params.name}`);
			return { content: [{ type: "text", text: `cancelled fork ${run.name}${run.worktree ? ` (worktree ${run.worktree} kept)` : ""}` }], details: { name: run.name } };
		},
	});
	pi.registerTool({
		name: "fork_resume",
		label: "Fork resume",
		description: "Restart a background fork that a reload, a crash or the end of the session stopped, on its own session and worktree, in the background.",
		promptSnippet: "Resume a lost background fork",
		parameters: Type.Object({ name: Type.String({ description: "Name of the lost fork" }) }),
		async execute(toolCallId, params, _signal, _onUpdate, ctx) {
			if (process.env.PI_HERDSMAN_MAILBOX || process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can resume a fork.");
			const resumable = registry.all().filter(canResume);
			const run = resumable.filter((candidate) => candidate.name === params.name).at(-1);
			if (!run?.files) throw new Error(`no lost fork ${params.name} to resume. Resumable: ${resumable.map((candidate) => candidate.name).join(", ") || "none"}`);
			if (run.tree) await restoreWorktree(run.tree);
			registry.update(run.id, { state: "running", endedAt: undefined, endedBy: undefined });
			const message = `${run.tree ? `Your worktree: ${run.tree.path}\n` : ""}Your session stopped before you finished. Continue the task from where you left off, and end with your OUTCOME line.`;
			startRun(ctx, { id: run.id, name: run.name, ref: `rc-fork-${run.name}-${toolCallId}`, role: ROLES[run.role as Role["name"]], tree: run.tree, target: run.target, files: run.files, background: true }, { message, resume: true });
			return { content: [{ type: "text", text: `resumed fork ${run.name} (background)` }], details: { name: run.name, runId: run.id, background: true } };
		},
	});
	pi.registerTool({
		name: "fork_steer",
		label: "Fork steer",
		description: "Send a message to a live background fork. It reaches the fork after its current tool calls, before its next model call.",
		promptSnippet: "Steer a live background fork",
		parameters: Type.Object({ name: Type.String({ description: "Name of the background fork" }), message: Type.String({ description: "What the fork should do differently or also do" }) }),
		async execute(_toolCallId, params) {
			if (process.env.PI_HERDSMAN_MAILBOX || process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can steer a fork.");
			await background.steer(params.name, params.message);
			return { content: [{ type: "text", text: `steered fork ${params.name}` }], details: { name: params.name } };
		},
	});
}
