// Adds the fork tool, which runs a delegate on a copy of this session that shares its prompt cache, or a cold worker on a cheaper model. A writer works in a git worktree and lands its commits through the merge queue.
// Config: llmPrompts.forks in pi settings: mcpProxy (true: a fork uses main's MCP servers), privateNames (regex of names a writer's commits may not land with), readMcp (array of {tool, argsMatch?}: extra MCP tools, as globs, a delegate may call when each argsMatch regex matches the whole of that string argument)
// Env: PI_CONTEXT_CHILD (set in a delegate, which cannot fork), PI_CONTEXT_ROLE and PI_CONTEXT_RUN_ID (set for a delegate), PI_CONTEXT_WORKTREE (set for a writer: its worktree, for hooks that resolve the session repo)
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { getAgentDir, type ExtensionAPI, type ExtensionContext, type ExtensionToolContext, type SessionEntry } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { parseOutcome, projectResult } from "./outcome.ts";
import { Background } from "./background.ts";
import { describeMain, lastPrefixHash, PREFIX_FILE, serveBridge, writeLeadPrefix, type BridgeOptions } from "./bridge.ts";
import { createWorktree, dropIfClean, gitOut, land, mainSnapshot, restoreWorktree, type Event, type Landing, type Worktree } from "./merge.ts";
import { checkReadMcp, coldCard, expandHome, readHandshake, ROLES, withReadMcp, type ReadMcp, type Role } from "./roles.ts";
import { tokens } from "./live-view.ts";
import { cacheLeftMs, FINISHED, isLive, registryOf, type Run, type RunState } from "./registry.ts";
import { RpcChild, type Turn, type UiAnswer, type UiRequest } from "./runner.ts";
import { retainSession } from "./usage-sessions.ts";

const holdsCall = (entry: SessionEntry, toolCallId: string) =>
	entry.type === "message" && entry.message.role === "assistant" && entry.message.content.some((block) => block.type === "toolCall" && block.id === toolCallId);

/** The entries before the assistant message holding the call: the part of the session the last request cached. */
export function seedEntries(branch: SessionEntry[], toolCallId: string): SessionEntry[] {
	const at = branch.findIndex((entry) => holdsCall(entry, toolCallId.split("/")[0]));
	return at < 0 ? branch : branch.slice(0, at);
}

/** The model a fork's `model` names: a provider/id as given, or a tier alias from the installed `pi-context/models.json`. */
export function resolveModel(model: string, agentDir = getAgentDir()): string {
	if (model.includes("/")) return model;
	let tiers: Record<string, string> = {};
	try {
		tiers = JSON.parse(fs.readFileSync(path.join(agentDir, "pi-context", "models.json"), "utf8"));
	} catch {}
	const [tier, effort] = model.split(":", 2);
	const resolved = tiers[tier];
	if (!resolved) throw new Error(`unknown model tier ${tier}: use provider/id or one of ${Object.keys(tiers).sort().join(", ")}`);
	return effort ? `${resolved}:${effort}` : resolved;
}

export function coldLabel(name: string, model: string, resolved: string): string {
	return `cold worker ${name} on ${model === resolved ? model : `${model} = ${resolved}`} (no shared context)`;
}

export type ColdOptions = { model: string; sessionDir: string; cardFile: string; skillsDir: string; session?: string };

/** The arguments of a cold worker: a fresh session, or `session` to continue, on its own model with only the role's skills, the role card in its system prompt and no MCP servers of its own. */
export function coldArgs(role: Role, { model, sessionDir, cardFile, skillsDir, session }: ColdOptions): string[] {
	const skills = role.skills.flatMap((skill) => ["--skill", path.join(skillsDir, skill)]);
	return ["--mode", "rpc", ...(session ? ["--session", session] : ["--session-dir", sessionDir]), "--model", model, "--no-skills", ...skills, "--append-system-prompt", cardFile, "--no-mcp"];
}

const FINISHED_MARK = "finished";

/** The `llmPrompts.forks` object of pi's settings. */
function forkSettings(pi: ExtensionAPI, ctx?: ExtensionContext): { mcpProxy?: boolean; privateNames?: string; readMcp: ReadMcp[] } {
	const forks = ((pi.getSettings?.() as { llmPrompts?: { forks?: object } } | undefined)?.llmPrompts?.forks ?? {}) as { mcpProxy?: boolean; privateNames?: string; readMcp?: unknown };
	const { valid, dropped } = checkReadMcp(forks.readMcp);
	const warning = `pi-context: dropped invalid llmPrompts.forks.readMcp entries: ${JSON.stringify(dropped)}`;
	if (dropped.length && ctx?.hasUI) ctx.ui.notify(warning, "warning");
	else if (dropped.length) process.stderr.write(`${warning}\n`);
	return { ...forks, readMcp: valid };
}

/** The session file a run's delegate wrote: the seed of a warm fork, or the newest session of a cold worker. */
export function sessionFileOf(files: string, cold: boolean): string | undefined {
	if (!cold) return fs.existsSync(path.join(files, "seed.jsonl")) ? path.join(files, "seed.jsonl") : undefined;
	const sessions = path.join(files, "session");
	if (!fs.existsSync(sessions)) return undefined;
	const found = fs.readdirSync(sessions, { recursive: true, encoding: "utf8" }).filter((file) => file.endsWith(".jsonl")).map((file) => path.join(sessions, file));
	return found.sort((a, b) => fs.statSync(a).mtimeMs - fs.statSync(b).mtimeMs).at(-1);
}

/** Archives the full session outside the usage store and retains only the delegate's entries for accounting. */
export async function keepSession(files: string, cold: boolean, name: string, runId: string, agentDir = getAgentDir()): Promise<void> {
	const session = sessionFileOf(files, cold);
	if (!session) return;
	const handshake = cold ? undefined : readHandshake(path.join(files, "handshake.json"));
	if (!cold && handshake?.inherited === undefined) throw new Error("Cannot retain a warm session without its inherited boundary");
	await retainSession(session, `${name}-${runId}.jsonl`, handshake?.inherited ?? undefined, agentDir);
}

/** How long a finished fork's files stay, so its session and cost can still be read. */
export const KEEP_FINISHED_MS = 24 * 60 * 60_000;

/** Removes the files of forks that finished more than `KEEP_FINISHED_MS` ago. */
export function sweepFinished(root = path.join(getAgentDir(), "pi-context"), now = Date.now()): void {
	if (!fs.existsSync(root)) return;
	for (const dir of fs.readdirSync(root)) {
		const mark = path.join(root, dir, FINISHED_MARK);
		const stat = fs.statSync(mark, { throwIfNoEntry: false });
		if (stat && now - stat.mtimeMs > KEEP_FINISHED_MS) fs.rmSync(path.join(root, dir), { recursive: true, force: true });
	}
}

const WARMUP_MS = 60_000;
const warming = new Map<string, Promise<void>>();

/** Waits up to `WARMUP_MS` for the cold worker with the same prompt prefix `key` that is still on its first request, so this one reads its cache. Without one, this worker leads: the returned function ends its first request. */
export async function warmUp(key: string, onWait?: (waiting: boolean) => void, signal?: AbortSignal): Promise<() => void> {
	const leader = warming.get(key);
	if (!leader) {
		let release!: () => void;
		const first = new Promise<void>((resolve) => (release = resolve));
		warming.set(key, first);
		return () => {
			if (warming.get(key) === first) warming.delete(key);
			release();
		};
	}
	onWait?.(true);
	let timer: ReturnType<typeof setTimeout> | undefined;
	await Promise.race([leader, new Promise<void>((resolve) => {
		timer = setTimeout(resolve, WARMUP_MS);
		signal?.addEventListener("abort", () => resolve(), { once: true });
	})]);
	clearTimeout(timer);
	if (warming.get(key) === leader) warming.delete(key);
	onWait?.(false);
	return () => undefined;
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
	/** Keeps the run's files for `sweepFinished` to remove after `KEEP_FINISHED_MS`, so the finished run can continue. */
	continuable?: boolean;
	/** Receives the child once it has started. */
	onChild?: (child: RpcChild) => void;
	/** Runs while a cold worker waits for another to write the prompt cache it shares, and with false once it stops waiting. */
	onWarmup?: (waiting: boolean) => void;
	/** Runs after the first turn while the session is still open; `resume` prompts it again. */
	onTurn?: (turn: Turn) => Promise<void>;
};

/** Runs the role's session on a copy of the given entries with main's model, thinking level and directory, or as a cold worker with `model`, and returns its first turn. */
export async function runDelegate(pi: ExtensionAPI, ctx: ExtensionContext, { role, name, entries = [], message, signal, command, runId = newRunId(), model, mcp, worktree, repo, cwd, files = path.join(getAgentDir(), "pi-context", randomUUID()), resume, keep, continuable, onChild, onWarmup, onTurn }: DelegateOptions): Promise<Turn & { prefix?: "match" | "mismatch" } & Pick<Run, "lastRequestAt" | "context">> {
	if (!ctx.model) throw new Error("Cannot start a delegate without a model.");
	const session = resume && model ? sessionFileOf(files, true) : undefined;
	if (resume && model && !session) throw new Error("The cold worker's session is gone.");
	const agentDir = getAgentDir();
	registryOf().update(runId, { files, model });
	const seed = path.join(files, "seed.jsonl");
	const handshake = path.join(files, "handshake.json");
	const cardFile = path.join(files, "card.md");
	const sessionDir = path.join(files, "session");
	const inherited = model ? undefined : resume ? readHandshake(handshake)?.inherited : (entries.at(-1)?.id ?? null);
	if (!model && inherited === undefined) throw new Error("Cannot resume a warm fork without its inherited boundary");
	let bridge: Awaited<ReturnType<typeof serveBridge>> | undefined;
	let child: RpcChild | undefined;
	let warmed: (() => void) | undefined;
	try {
		fs.mkdirSync(files, { recursive: true, mode: 0o700 });
		fs.rmSync(path.join(files, FINISHED_MARK), { force: true });
		let prefix: "match" | "mismatch" | undefined;
		const onPrefix = model ? undefined : (hash: string) => void (prefix = hash === lastPrefixHash() ? "match" : "mismatch");
		const { readMcp } = forkSettings(pi, ctx);
		const allowed = withReadMcp(role, readMcp);
		bridge = mcp && (await serveBridge(files, { role: allowed, execute: mcp, onPrefix }));
		const main = bridge && describeMain(pi, ctx, model ? allowed : undefined);
		fs.writeFileSync(handshake, JSON.stringify({ role: role.name, worktree, repo, inherited, readMcp, bridge: bridge && { ...main, socket: bridge.socket } }), { mode: 0o600 });
		if (model) fs.writeFileSync(cardFile, coldCard(role), { mode: 0o600 });
		else if (!resume) {
			writeLeadPrefix(files);
			fs.writeFileSync(seed, jsonl([{ ...ctx.sessionManager.getHeader(), id: randomUUID(), ...(cwd && { cwd }), piContextFork: { parentSessionId: ctx.sessionManager.getHeader()?.id, inherited } }, ...entries]), { mode: 0o600 });
		}
		const childCwd = (model && worktree) || cwd || ctx.cwd;
		child = RpcChild.start({
			command,
			cwd: childCwd,
			args: model
				? coldArgs(role, { model, sessionDir, cardFile, skillsDir: path.join(agentDir, "skills"), session })
				: ["--mode", "rpc", "--session", seed, "--model", `${ctx.model.provider}/${ctx.model.id}`, "--thinking", pi.getThinkingLevel(), ...(bridge ? ["--no-mcp"] : [])],
			env: { ...process.env, PI_CONTEXT_CHILD: handshake, PI_CONTEXT_ROLE: role.name, PI_CONTEXT_RUN_ID: runId, PI_CONTEXT_WORKTREE: worktree },
			signal,
			onUi: relayDialog(name, ctx),
		});
		onChild?.(child);
		const last: Pick<Run, "lastRequestAt" | "context"> = {};
		child.watch((record) => {
			if (record.type !== "message_end" || record.message?.role !== "assistant") return;
			const { input = 0, output = 0, cacheRead = 0, cacheWrite = 0 } = record.message.usage ?? {};
			Object.assign(last, { lastRequestAt: Date.now(), context: input + output + cacheRead + cacheWrite });
			warmed?.();
		});
		if (model && !session) warmed = await warmUp(JSON.stringify([model, role.name, coldCard(role), role.skills, childCwd, main]), onWarmup, signal);
		const turn = await child.prompt(model || resume ? message : `${role.card}\n\n${message}`);
		const reported = !model && !bridge && readText(path.join(files, PREFIX_FILE));
		if (reported) prefix = reported === lastPrefixHash() ? "match" : "mismatch";
		await onTurn?.(turn);
		return { ...turn, prefix, ...last };
	} finally {
		warmed?.();
		await child?.close();
		await bridge?.close();
		let retained = true;
		try { if (child) await keepSession(files, Boolean(model), name, runId, agentDir); } catch (error) {
			retained = false;
			console.warn(`pi-context: could not retain session in ${files}; keeping the full run for recovery: ${String(error)}`);
		}
		const kept = keep?.();
		if (retained && !kept && continuable && child) fs.writeFileSync(path.join(files, FINISHED_MARK), "");
		else if (retained && !kept) fs.rmSync(files, { recursive: true, force: true });
	}
}

const WORKTREES = "worktrees";

/** The toplevel of the git checkout at `dir`, or undefined when it is not one. */
const checkoutOf = (dir: string) => gitOut(dir, "rev-parse", "--show-toplevel").catch(() => undefined);
const isPrimaryCheckout = async (dir: string) => {
	const [gitDir, commonDir] = (await gitOut(dir, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")).split("\n");
	return gitDir === commonDir;
};

const sameDir = (a: string, b: string) => fs.realpathSync(a) === fs.realpathSync(b);

/** Whether a lost run's session is still there to continue. */
export const canResume = (run: Run): boolean => run.state === "lost" && run.background && Boolean(run.files && sessionFileOf(run.files, Boolean(run.model)));

/** Whether a finished run's session is still there to continue with a new task. */
export const canContinue = (run: Run): boolean => FINISHED.includes(run.state) && Boolean(run.files && sessionFileOf(run.files, Boolean(run.model)));

/** A line naming the latest finished fork of `role` in `dir` whose prompt cache is still warm, or undefined. */
function cachedHint(runs: Run[], role: string, dir: string, now = Date.now()): string | undefined {
	const cached = runs.filter((run) => run.role === role && (run.target ?? run.cwd) === dir && (cacheLeftMs(run, now) ?? 0) > 0 && canContinue(run));
	const run = cached.sort((a, b) => (a.lastRequestAt ?? 0) - (b.lastRequestAt ?? 0)).at(-1);
	return run && `fork ${run.name} finished ${Math.floor((now - (run.endedAt ?? now)) / 60_000)}m ago with ${tokens(run.context ?? 0)} ctx, still cached: fork_resume({name, task}) is cheaper`;
}

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

/** Tells a writer where its commits land and that it must not name its own checkout or other worktrees, or that it writes in place in `dir`, which is not a git checkout. Empty for a reader. */
const worktreeLine = (tree?: Worktree, dir?: string) =>
	tree ? `Your worktree: ${tree.path}. Your commits land on ${tree.branch} in ${tree.repo} when you finish. Do not name ${tree.repo} or other worktrees in commands.\n` : dir ? `${dir} is not a git checkout, so you have no worktree: write in place there. Nothing lands.\n` : "";

/** What a delegate's reply says about its work: done, or an outcome that stops the landing. A reply without a valid OUTCOME line counts as failed. */
function replyEvent(turn: Turn): Extract<Event, { type: "fork-done" | "fork-failed" | "fork-blocked" }> {
	const reason = turn.error ?? projectResult(turn.text);
	const code = parseOutcome(turn.text)?.code;
	if (turn.error || code === "failed") return { type: "fork-failed", reason };
	if (code === "blocked-on-user") return { type: "fork-blocked", reason };
	return code === "done" || code === "found-it" ? { type: "fork-done" } : { type: "fork-failed", reason: `the reply has no valid OUTCOME line\n${reason}` };
}

function finalState(code: string | undefined, landing: Landing | undefined): RunState {
	if (code === "failed") return "failed";
	if (code === "blocked-on-user" || landing?.state === "escalated") return "blocked";
	return code === "found-it" || code === "done" ? code : "failed";
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
		const onTurn = tree && (async (turn: Turn) => {
			if (turn.error) return;
			registry.update(runId, { state: "landing" });
			merged.landing = await land({ tree, first: replyEvent(turn), privateNames: forkSettings(pi).privateNames });
		});
		const mcp = run.model || forkSettings(pi).mcpProxy === true ? async (tool: string, args: unknown) => {
			const { result, isError } = await ctx.executeTool(tool, args, { signal: runSignal });
			return { content: result.content, details: result.details, structuredContent: result.structuredContent, isError };
		} : undefined;
		const keep = () => registry.get(runId)?.state === "lost";
		const running = runDelegate(pi, ctx, { role: run.role, name, ...delegate, signal: runSignal, command, runId, model: run.model, mcp, worktree: tree?.path ?? (run.role.writes ? (run.target ?? ctx.cwd) : undefined), repo: tree?.repo, cwd: run.target, files: run.files, keep, continuable: true, onChild: run.background ? (child) => background.attach(runId, child) : undefined, onWarmup: (waiting) => background.view?.note(runId, waiting ? "waiting for cache" : undefined), onTurn });
		if (run.background) {
			const onEnd = async (turn: Awaited<typeof running>) => {
				const current = registry.get(runId);
				if (!current || !isLive(current) || runSignal?.aborted) return;
				const end = { ...endOf(ref, turn, merged.landing), lastRequestAt: turn.lastRequestAt, context: turn.context };
				const text = turn.error ?? turn.text;
				const note = merged.landing && tree ? `[merge: ${describeLanding(merged.landing, tree)}]` : tree && (await dropIfClean(tree)) ? "[merge: worktree removed: clean]" : undefined;
				background.finish(ctx, runId, end, text, note);
				pi.appendEntry("result-cap", { ref: end.ref, text });
			};
			const onFail = async (error: unknown) => {
				if (registry.get(runId)?.state === "lost" || runSignal?.aborted) return;
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
			"Run a delegate on a copy of this session, so it knows everything you know and reuses the prompt cache. Give it one self-contained task. A reader (the default) only reads. A writer works in its own git worktree and its commits are rebased, tested and fast-forwarded onto the current branch. A writer can only work in its own worktree, so give each branch its own writer. target points either role at another directory. A writer whose directory is not a git checkout writes in place, and nothing lands. It blocks until the delegate replies with an OUTCOME line and the work has landed. With background true it returns at once and the result arrives as a message when the delegate finishes.",
		promptSnippet: "Run a read-only or worktree-writing delegate on a copy of this session and wait for its reply",
		parameters: Type.Object({
			task: Type.String({ description: "What the delegate should find out or check" }),
			role: Type.Optional(Type.Union([Type.Literal("reader"), Type.Literal("writer")], { description: "reader (default) reads only, writer commits in its own worktree" })),
			name: Type.Optional(Type.String({ pattern: "^[a-z0-9-]{1,24}$", description: "Short name for the delegate" })),
			background: Type.Optional(Type.Boolean({ description: "Return at once and receive the result later as a message, so you can keep working" })),
			target: Type.Optional(Type.String({ description: "Path of another directory, git checkout or worktree to read or land in, instead of this session's" })),
			model: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][\\w./:@-]*$", description: "Run as a cold worker on this model: provider/id (optionally :thinking) or a tier name such as sol or opus. Any model starts an empty session with no context and no prompt cache from you, so the task must be self-contained" })),
		}),
		async execute(toolCallId, params, signal, _onUpdate, ctx) {
			if (process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can fork.");
			if (!ctx.model) throw new Error("Cannot fork without a model.");
			sweepFinished();
			const role: Role = ROLES[params.role ?? "reader"];
			const name = params.name ?? `fork-${randomUUID().slice(0, 6)}`;
			const dir = path.resolve(ctx.cwd, expandHome(params.target ?? "."));
			if (!fs.existsSync(dir)) throw new Error(`target ${params.target} does not exist`);
			const checkout = await checkoutOf(dir);
			if (role.writes && params.target === undefined && checkout && (await isPrimaryCheckout(checkout))) throw new Error(`${checkout} is a primary checkout: change_dir to a worktree first`);
			const home = params.target === undefined ? ctx.cwd : role.writes ? (checkout ?? dir) : dir;
			const target = sameDir(home, ctx.cwd) ? undefined : home;
			const model = params.model && resolveModel(params.model);
			const tree = role.writes && checkout ? await createWorktree(home, path.join(getAgentDir(), "pi-context", WORKTREES), name) : undefined;
			const entries = seedEntries(ctx.sessionManager.getBranch(), toolCallId);
			const runId = newRunId();
			const ref = `rc-fork-${name}-${toolCallId}`;
			const files = path.join(getAgentDir(), "pi-context", randomUUID());
			const cold = params.model && model ? coldLabel(name, params.model, model) : undefined;
			const hint = cachedHint(registry.all(), role.name, target ?? ctx.cwd);
			const withHint = (text: string) => (hint ? `${text}\n${hint}` : text);
			registry.start({ id: runId, name, role: role.name, model, background: Boolean(params.background), state: "running", task: params.task, worktree: tree?.path, branch: tree?.branch, tree, target, cwd: ctx.cwd, startedAt: Date.now() });
			const message = `${worktreeLine(tree, role.writes ? home : undefined)}Task: ${params.task}`;
			const { running, merged } = startRun(ctx, { id: runId, name, ref, role, tree, target, model, files, background: Boolean(params.background), signal }, { entries, message });
			if (params.background) {
				return { content: [{ type: "text", text: withHint(`started ${cold ?? `fork ${name}`} (background)`) }], details: { name, runId, background: true } };
			}
			let turn: Awaited<typeof running>;
			try {
				turn = await running;
			} catch (error) {
				registry.update(runId, { state: "failed", endedAt: Date.now() });
				throw new Error(`fork ${name} failed: ${error instanceof Error ? error.message : String(error)}${await treeNote(tree)}`, { cause: error });
			}
			const request = { lastRequestAt: turn.lastRequestAt, context: turn.context };
			if (turn.error) {
				registry.update(runId, { state: "failed", endedAt: Date.now(), ...request });
				throw new Error(`fork ${name} failed: ${turn.error}${await treeNote(tree)}`);
			}
			const end = endOf(ref, turn, merged.landing);
			registry.update(runId, { ...end, endedAt: Date.now(), ...request });
			pi.appendEntry("result-cap", { ref: end.ref, text: turn.text });
			background.pinForeground(ctx, { id: runId, name }, turn.text);
			const cache = `${cold ? `${cold}, ` : ""}${turn.prefix === "mismatch" ? "prefix mismatch, " : ""}${turn.firstUsage ? `cache ${turn.firstUsage.cacheRead}/${turn.firstUsage.cacheWrite}, ` : ""}`;
			return {
				content: [{ type: "text", text: withHint(`${projectResult(turn.text)}\n[fork ${name}: ${cache}ref ${end.ref}]${merged.landing && tree ? `\n[merge: ${describeLanding(merged.landing, tree)}]` : ""}`) }],
				details: { name, role: role.name, outcome: end.outcome, usage: turn.usage, firstUsage: turn.firstUsage, prefix: turn.prefix, merge: merged.landing },
			};
		},
	});
	/** Gives a finished run a new task on its own session, model and role, in the background. */
	async function continueRun(ctx: ExtensionToolContext, name: string, task: string, toolCallId: string) {
		sweepFinished();
		const continuable = registry.all().filter(canContinue);
		const run = continuable.filter((candidate) => candidate.name === name).at(-1);
		if (!run?.files) throw new Error(`no finished fork ${name} to continue. Continuable: ${continuable.map((candidate) => candidate.name).join(", ") || "none"}`);
		background.resolveForkAsks(ctx, run.name);
		const tree = run.tree && (fs.existsSync(run.tree.path) ? { ...run.tree, snapshot: await mainSnapshot(run.tree.repo) } : await createWorktree(run.tree.repo, path.join(getAgentDir(), "pi-context", WORKTREES), run.name));
		registry.update(run.id, { state: "running", task, background: true, tree, worktree: tree?.path, branch: tree?.branch, startedAt: Date.now(), endedAt: undefined, endedBy: undefined, outcome: undefined, notify: undefined });
		const message = `${worktreeLine(tree)}Task: ${task}`;
		startRun(ctx, { id: run.id, name: run.name, ref: `rc-fork-${run.name}-${toolCallId}`, role: ROLES[run.role as Role["name"]], tree, target: run.target ?? run.cwd, model: run.model, files: run.files, background: true }, { message, resume: true });
		return { content: [{ type: "text" as const, text: `continued fork ${run.name} (background)` }], details: { name: run.name, runId: run.id, background: true } };
	}

	pi.registerTool({
		name: "fork_cancel",
		label: "Fork cancel",
		description: "Stop a live background fork by name. A writer's worktree stays where it is.",
		promptSnippet: "Stop a live background fork",
		parameters: Type.Object({ name: Type.String({ description: "Name of the background fork" }) }),
		async execute(_toolCallId, params) {
			if (process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can fork.");
			const run = background.cancel(params.name);
			if (!run) throw new Error(`no live background fork ${params.name}`);
			return { content: [{ type: "text", text: `cancelled fork ${run.name}${run.worktree ? ` (worktree ${run.worktree} kept)` : ""}` }], details: { name: run.name } };
		},
	});
	pi.registerTool({
		name: "fork_resume",
		label: "Fork resume",
		description:
			"Without task, restart a background fork that a reload, a crash or the end of the session stopped, on its own session and worktree. With task, give a finished fork (done, found-it, blocked or failed), warm or cold, a new task on its own session, model and role: a reader works in its old directory, a writer in a new worktree from the current branch of its checkout, or its kept one. Both run in the background.",
		promptSnippet: "Resume a lost background fork, or give a finished fork a new task",
		promptGuidelines: [
			"Use fork_resume with task instead of fork when a finished fork of the same role and directory already holds the context the task needs, and its prompt cache is still warm: the fork tool's result names such a fork.",
		],
		parameters: Type.Object({
			name: Type.String({ description: "Name of the lost or finished fork" }),
			task: Type.Optional(Type.String({ description: "A new task for a finished fork. Without it, a lost fork continues its own task" })),
		}),
		async execute(toolCallId, params, _signal, _onUpdate, ctx) {
			if (process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can resume a fork.");
			if (params.task !== undefined) return continueRun(ctx, params.name, params.task, toolCallId);
			const resumable = registry.all().filter(canResume);
			const run = resumable.filter((candidate) => candidate.name === params.name).at(-1);
			if (!run?.files) throw new Error(`no lost fork ${params.name} to resume. Resumable: ${resumable.map((candidate) => candidate.name).join(", ") || "none"}`);
			background.resolveForkAsks(ctx, run.name);
			if (run.tree) await restoreWorktree(run.tree);
			registry.update(run.id, { state: "running", endedAt: undefined, endedBy: undefined });
			const message = `${worktreeLine(run.tree)}Your session stopped before you finished. Continue the task from where you left off, and end with your OUTCOME line.`;
			startRun(ctx, { id: run.id, name: run.name, ref: `rc-fork-${run.name}-${toolCallId}`, role: ROLES[run.role as Role["name"]], tree: run.tree, target: run.target, model: run.model, files: run.files, background: true }, { message, resume: true });
			return { content: [{ type: "text", text: `resumed fork ${run.name} (background)` }], details: { name: run.name, runId: run.id, background: true } };
		},
	});
	pi.registerTool({
		name: "fork_steer",
		label: "Fork steer",
		description: "Send a message to a live background fork. It reaches the fork after its current tool calls, before its next model call.",
		promptSnippet: "Steer a live background fork",
		parameters: Type.Object({ name: Type.String({ description: "Name of the background fork" }), message: Type.String({ description: "What the fork should do differently or also do" }) }),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			if (process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can steer a fork.");
			await background.steer(params.name, params.message);
			background.resolveForkAsks(ctx, params.name);
			return { content: [{ type: "text", text: `steered fork ${params.name}` }], details: { name: params.name } };
		},
	});
}
