// Adds the fork tool, which runs a delegate on a copy of this session that shares its prompt cache, or a cold worker on a cheaper model. A writer works in a git worktree and lands its commits through the merge queue.
// Config: llmPrompts.forks in pi settings: mcpProxy (true: a fork uses main's MCP servers), privateNames (regex of names a writer's commits may not land with), memoryMax and cpuQuota (systemd limits of one fork and its processes, defaulting to a quarter of the host's memory and half its cores), readMcp (array of {tool, argsMatch?}: extra MCP tools, as globs, a delegate may call when each argsMatch regex matches the whole of that string argument), checkInMinutes (see background.ts)
// Config: pi-context/forks.json in the pi agent directory, written by llm-prompts install from `max_live` under `[forks]` in config.toml (most forks that run at once, default 10: more wait in a queue)
// Env: PI_CONTEXT_CHILD (set in a delegate, which cannot fork), PI_CONTEXT_ROLE and PI_CONTEXT_RUN_ID (set for a delegate), PI_CONTEXT_WORKTREE (set for a writer: its worktree, for hooks that resolve the session repo)
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { buildSessionContext, defineTool, generateSummary, getAgentDir, type AgentToolResult, type ExtensionAPI, type ExtensionContext, type ExtensionToolContext, type SessionEntry } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { parseOutcome, projectResult } from "./outcome.ts";
import { replyText } from "./reply.ts";
import { Background, RESULTS_TYPE, Slots } from "./background.ts";
import { describeMain, LEAD_PREFIX_FILE, serveBridge, writeLeadPrefix, type BridgeOptions } from "./bridge.ts";
import { createWorktree, dropIfClean, gitOut, land, restoreWorktree, resumeWorktree, type Event, type Landing, type Worktree } from "./merge.ts";
import { checkReadMcp, coldCard, expandHome, readHandshake, ROLES, withReadMcp, type ReadMcp, type Role } from "./roles.ts";
import { findModel, tokens } from "./live-view.ts";
import { cacheLeftMs, cacheText, canResume, FINISHED, isLive, mainToolsContext, recordMainTools, registryOf, reloadRequested, sessionFileOf, type Run, type RunState } from "./registry.ts";
import type { ForkLimits } from "./cap.ts";
import { RpcChild, type Turn, type UiAnswer, type UiRequest } from "./runner.ts";
import { retainSession } from "./usage-sessions.ts";

const holdsCall = (entry: SessionEntry, toolCallId: string) =>
	entry.type === "message" && entry.message.role === "assistant" && entry.message.content.some((block) => block.type === "toolCall" && block.id === toolCallId);

const SAVED_STATE = new Set(["hide-tools", "pending-asks"]);

/** The entries before the assistant message holding the call, from the last compaction's first kept entry: what the lead's model saw in the last request. The saved state the extensions read from before it stays, chained ahead of them: tool visibility, pending asks, and each capped result a kept entry names. */
export function seedEntries(branch: SessionEntry[], toolCallId: string): SessionEntry[] {
	const at = branch.findIndex((entry) => holdsCall(entry, toolCallId.split("/")[0]));
	const sent = at < 0 ? branch : branch.slice(0, at);
	const compaction = [...sent].reverse().find((entry) => entry.type === "compaction");
	if (!compaction) return sent;
	const firstKept = Math.max(0, sent.findIndex((entry) => entry.id === compaction.firstKeptEntryId));
	const kept = sent.slice(firstKept);
	const keptText = JSON.stringify(kept);
	const isSaved = (entry: SessionEntry) =>
		entry.type === "custom" && (SAVED_STATE.has(entry.customType) || (entry.customType === "result-cap" && keptText.includes((entry.data as { ref: string }).ref)));
	const chained = [...sent.slice(0, firstKept).filter(isSaved), ...kept];
	return chained.map((entry, index) => ({ ...entry, parentId: chained[index - 1]?.id ?? null }));
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

/** A warm fork copies the session, so one over this many tokens of context starts cold with a summary instead. */
export const WARM_FORK_MAX_TOKENS = 150_000;

export type Summarize = (ctx: ExtensionContext, entries: SessionEntry[]) => Promise<string>;

/** Summarises the session entries with main's model. */
export const summarizeSession: Summarize = async (ctx, entries) => {
	const { model } = ctx;
	if (!model) throw new Error("Cannot summarize without a model.");
	const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
	if (!auth.ok) throw new Error(auth.error);
	return generateSummary(buildSessionContext(entries).messages, model, undefined, auth.apiKey, Object.fromEntries(Object.entries(auth.headers ?? {}).filter((header): header is [string, string] => header[1] !== null)), undefined, undefined, undefined, undefined, undefined, auth.env);
};

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
const STUB_SUFFIX = 'That is all the shared context. Once you have read it, call reply with {"outcome":"done","ref":""} and stop. Your specific task arrives next.';
/** The conversation a queued fork was called with, kept in its files so a resume starts it from that point. */
const QUEUED_ENTRIES = "queued-entries.json";

const DEFAULT_MAX_LIVE = 10;

type ForkSettings = { mcpProxy?: boolean; privateNames?: string; readMcp?: unknown } & ForkLimits;

/** The `llmPrompts.forks` object of pi's settings. */
const rawForkSettings = (pi: ExtensionAPI) => ((pi.getSettings?.() as { llmPrompts?: { forks?: object } } | undefined)?.llmPrompts?.forks ?? {}) as ForkSettings;

/** The most forks that run at once: `maxLive` of the installed `pi-context/forks.json` when it is a positive integer, else the default. */
const maxLive = (agentDir = getAgentDir()) => {
	let limit: unknown;
	try {
		limit = JSON.parse(fs.readFileSync(path.join(agentDir, "pi-context", "forks.json"), "utf8")).maxLive;
	} catch {}
	return Number.isInteger(limit) && (limit as number) > 0 ? (limit as number) : DEFAULT_MAX_LIVE;
};

function forkSettings(pi: ExtensionAPI, ctx?: ExtensionContext): { mcpProxy?: boolean; privateNames?: string; readMcp: ReadMcp[] } & ForkLimits {
	const forks = rawForkSettings(pi);
	const { valid, dropped } = checkReadMcp(forks.readMcp);
	const warning = `pi-context: dropped invalid llmPrompts.forks.readMcp entries: ${JSON.stringify(dropped)}`;
	if (dropped.length && ctx?.hasUI) ctx.ui.notify(warning, "warning");
	else if (dropped.length) process.stderr.write(`${warning}\n`);
	return { ...forks, readMcp: valid };
}

/** Archives the full session outside the usage store and retains only the delegate's entries for accounting. */
export async function keepSession(files: string, cold: boolean, name: string, runId: string, agentDir = getAgentDir()): Promise<void> {
	const session = sessionFileOf(files, cold);
	if (!session) return;
	const handshake = readHandshake(path.join(files, "handshake.json"));
	if (!cold && handshake?.inherited === undefined) throw new Error("Cannot retain a warm session without its inherited boundary");
	await retainSession(session, `${name}-${runId}.jsonl`, (cold ? handshake?.billedFrom : handshake?.inherited) ?? undefined, agentDir);
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
export async function runDelegate(pi: ExtensionAPI, ctx: ExtensionContext, { role, name, entries = [], message, signal, command, runId = newRunId(), model, mcp, worktree, repo, cwd, files = path.join(getAgentDir(), "pi-context", randomUUID()), resume, keep, continuable, onChild, onWarmup, onTurn }: DelegateOptions): Promise<Turn & Pick<Run, "lastRequestAt" | "context">> {
	if (!ctx.model) throw new Error("Cannot start a delegate without a model.");
	const session = resume && model ? sessionFileOf(files, true) : undefined;
	if (resume && model && !session) throw new Error("The cold worker's session is gone.");
	const agentDir = getAgentDir();
	registryOf().update(runId, { files, model });
	const seed = path.join(files, "seed.jsonl");
	const handshake = path.join(files, "handshake.json");
	const cardFile = path.join(files, "card.md");
	const sessionDir = path.join(files, "session");
	const started = resume ? readHandshake(handshake) : undefined;
	const inherited = resume ? started?.inherited : model ? undefined : (entries.at(-1)?.id ?? null);
	const warm = { model: started?.model ?? `${ctx.model.provider}/${ctx.model.id}`, thinking: started?.thinking ?? pi.getThinkingLevel() };
	if (!model && inherited === undefined) throw new Error("Cannot resume a warm fork without its inherited boundary");
	let bridge: Awaited<ReturnType<typeof serveBridge>> | undefined;
	let child: RpcChild | undefined;
	let warmed: (() => void) | undefined;
	try {
		fs.mkdirSync(files, { recursive: true, mode: 0o700 });
		fs.rmSync(path.join(files, FINISHED_MARK), { force: true });
		const { readMcp, memoryMax, cpuQuota } = forkSettings(pi, ctx);
		const allowed = withReadMcp(role, readMcp);
		bridge = mcp && (await serveBridge({ role: allowed, execute: mcp }));
		const main = bridge && describeMain(pi, ctx, model ? allowed : undefined);
		fs.writeFileSync(handshake, JSON.stringify({ role: role.name, worktree, repo, inherited, ...(!model && warm), ...(model && started && { billedFrom: started.billedFrom, cacheKey: started.cacheKey }), readMcp, bridge: bridge && { ...main, socket: bridge.socket } }), { mode: 0o600 });
		if (model) fs.writeFileSync(cardFile, coldCard(role), { mode: 0o600 });
		else if (!resume) {
			writeLeadPrefix(files);
			fs.writeFileSync(seed, jsonl([{ ...ctx.sessionManager.getHeader(), id: randomUUID(), ...(cwd && { cwd }), piContextFork: { parentSessionId: ctx.sessionManager.getHeader()?.id, inherited } }, ...entries]), { mode: 0o600 });
		}
		const childCwd = (model && worktree) || cwd || ctx.cwd;
		child = RpcChild.start({
			command,
			limits: { memoryMax, cpuQuota },
			cwd: childCwd,
			args: model
				? coldArgs(role, { model, sessionDir, cardFile, skillsDir: path.join(agentDir, "skills"), session })
				: ["--mode", "rpc", "--session", seed, "--model", warm.model, "--thinking", warm.thinking, ...(bridge ? ["--no-mcp"] : [])],
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
		await onTurn?.(turn);
		return { ...turn, ...last };
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

const sameDir = (a: string, b: string) => fs.realpathSync(a) === fs.realpathSync(b);

/** Whether a finished run's session is still there to continue with a new task. */
export const canContinue = (run: Run): boolean => FINISHED.includes(run.state) && Boolean(run.files && sessionFileOf(run.files, Boolean(run.model)));

/** The latest finished run named `name` whose session is still there. */
export function finishedRun(runs: Run[], name: string): Run & { files: string } {
	const finished = runs.filter(canContinue);
	const run = finished.filter((candidate) => candidate.name === name).at(-1);
	if (!run?.files) throw new Error(`no finished fork ${name}. Finished: ${finished.map((candidate) => candidate.name).join(", ") || "none"}`);
	return { ...run, files: run.files };
}

/** Copies the session of the finished run in `source` into the new run directory `files`, for a child to continue: a warm seed or a cold worker's newest session, under a new header id with the source as its parent, with the source's handshake and lead prefix. The last copied entry becomes the warm handshake's `inherited` or the cold one's `billedFrom`, so the child is billed only for its own turns, and a cold copy sends its source's prompt cache key. */
export function copySession(source: string, files: string, cold: boolean): void {
	const session = sessionFileOf(source, cold);
	if (!session) throw new Error(`the session in ${source} is gone`);
	const copy = cold ? path.join(files, "session", path.basename(session)) : path.join(files, "seed.jsonl");
	fs.mkdirSync(path.dirname(copy), { recursive: true, mode: 0o700 });
	const [header, ...rest] = fs.readFileSync(session, "utf8").split("\n").filter(Boolean);
	const parent = JSON.parse(header);
	const inherited = rest.length ? (JSON.parse(rest.at(-1)!).id as string) : null;
	const forked = { ...parent.piContextFork, parentSessionId: parent.id, ...(!cold && { inherited }) };
	fs.writeFileSync(copy, `${[JSON.stringify({ ...parent, id: randomUUID(), piContextFork: forked }), ...rest].join("\n")}\n`, { mode: 0o600 });
	const handshake = readText(path.join(source, "handshake.json"));
	const sourceHandshake = handshake ? JSON.parse(handshake) : undefined;
	const boundary = cold ? { billedFrom: inherited, cacheKey: sourceHandshake?.cacheKey ?? parent.id } : { inherited };
	if (sourceHandshake) fs.writeFileSync(path.join(files, "handshake.json"), JSON.stringify({ ...sourceHandshake, ...boundary }), { mode: 0o600 });
	if (fs.existsSync(path.join(source, LEAD_PREFIX_FILE))) fs.copyFileSync(path.join(source, LEAD_PREFIX_FILE), path.join(files, LEAD_PREFIX_FILE));
}

const PER_MILLION_TOKENS = 1_000_000;
const CHARS_PER_TOKEN = 4;

type Price = { input: number; cacheRead: number };
/** The prices of a cold worker's model, or of the session's model for a warm fork. Undefined where the registry does not know them. */
const priceOf = (ctx: ExtensionContext, model?: string): Price | undefined => (model ? findModel(model, ctx.modelRegistry)?.cost : ctx.model?.cost);

/** The prices of the model a finished run resumes on: a cold worker's, or the one a warm fork's handshake saved. */
const savedPrice = (ctx: ExtensionContext, run: Run): Price | undefined => {
	const model = run.model ?? (run.files ? readHandshake(path.join(run.files, "handshake.json"))?.model : undefined);
	return model ? priceOf(ctx, model) : undefined;
};

/** What a fresh fork on `model` would pay for its starting context, in dollars: a warm fork reads main's cached context, a cold worker writes its card and task uncached. Undefined without the model's prices. */
function freshStartCost(ctx: ExtensionContext, role: Role, task: string, model?: string): number | undefined {
	const price = priceOf(ctx, model);
	if (!price) return undefined;
	const tokensRead = model ? Math.ceil((coldCard(role).length + task.length) / CHARS_PER_TOKEN) : (ctx.getContextUsage()?.tokens ?? 0);
	return (tokensRead * (model ? price.input : price.cacheRead)) / PER_MILLION_TOKENS;
}

/** Lines naming every finished fork `fork_resume` would pick by name, of `role` in `dir`, whose prompt cache is still warm and whose context costs less to read from the cache, at its own model's price, than `freshCost`, newest first, each with its context size and cache time left, or undefined. */
function cachedHint(runs: Run[], role: string, dir: string, priceOfRun: (run: Run) => Price | undefined, freshCost: number | undefined, now = Date.now()): string | undefined {
	if (freshCost === undefined) return undefined;
	const picked = new Map(runs.filter(canContinue).map((run) => [run.name, run]));
	const cached = [...picked.values()].filter((run) => {
		const price = priceOfRun(run);
		return run.role === role && (run.target ?? run.cwd) === dir && (cacheLeftMs(run, now) ?? 0) > 0 && price !== undefined && ((run.context ?? 0) * price.cacheRead) / PER_MILLION_TOKENS < freshCost;
	});
	if (!cached.length) return undefined;
	const lines = cached.sort((a, b) => (b.lastRequestAt ?? 0) - (a.lastRequestAt ?? 0)).map((run) => `fork ${run.name}: ${tokens(run.context ?? 0)} ctx, ${cacheText(cacheLeftMs(run, now) ?? 0)}`);
	return [...lines, "fork_resume({name, task}) is cheaper than a fresh fork"].join("\n");
}

/** The prompt cache key the session in run directory `files` sends: a cold worker's own, else main's from its lead prefix. */
const cacheKeyOf = (files: string): string | undefined => {
	const key = (name: string, field: string): string | undefined => {
		const text = readText(path.join(files, name));
		return text ? JSON.parse(text)[field] : undefined;
	};
	return key("handshake.json", "cacheKey") ?? key(LEAD_PREFIX_FILE, "prompt_cache_key");
};

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
	tree ? `Your worktree: ${tree.path}. ${tree.own ? `Your branch is ${tree.branch}, from ${tree.base}. Push it with git push when you finish: that is the landing.` : `Your commits land on ${tree.branch} in ${tree.repo} when you finish.`} Do not name ${tree.repo} or other worktrees in commands.\n` : dir ? `${dir} is not a git checkout, so you have no worktree: write in place there. Nothing lands.\n` : "";

/** The delegate's reply: its reply call's arguments in the OUTCOME format, or else its last text. */
const replyOf = (turn: Turn): string => (turn.reply ? replyText(turn.reply) : turn.text);

/** The code and notify flag of the delegate's reply call, or else of its OUTCOME line. */
const outcomeOf = (turn: Turn): { code: string; notify: boolean } | undefined => (turn.reply ? { code: turn.reply.outcome, notify: Boolean(turn.reply.notify) } : parseOutcome(turn.text));

/** What a delegate's reply says about its work: done, or an outcome that stops the landing. A reply without a reply call or a valid OUTCOME line counts as failed. */
function replyEvent(turn: Turn): Extract<Event, { type: "fork-done" | "fork-failed" | "fork-blocked" }> {
	const reason = turn.error ?? projectResult(replyOf(turn));
	const code = outcomeOf(turn)?.code;
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
	const parsed = outcomeOf(turn);
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

export function registerFork(pi: ExtensionAPI, command?: string[], background = new Background(pi), summarize: Summarize = summarizeSession) {
	const registry = registryOf();
	const summaries = new Map<string, Promise<string>>();

	/** The summary of the session up to `entries`. Forks of the same snapshot share the call that is running. Shortcut: the call has no abort signal, so a cancelled fork lets it finish, upgrade when a call can be shared by refcount. */
	function summaryOf(ctx: ExtensionContext, entries: SessionEntry[]): Promise<string> {
		const key = `${ctx.sessionManager.getHeader()?.id}:${entries.at(-1)?.id}`;
		const running = summaries.get(key) ?? summarize(ctx, entries).finally(() => summaries.delete(key));
		summaries.set(key, running);
		return running;
	}
	const slots = new Slots(maxLive);
	/** Starts the delegate of a registered run in the background, which reports its end to `background`. */
	function startRun(ctx: ExtensionToolContext, run: { id: string; name: string; ref: string; role: Role; tree?: Worktree; target?: string; model?: string; files: string }, delegate: Pick<DelegateOptions, "entries" | "message" | "resume">) {
		const { id: runId, name, ref, tree } = run;
		const merged: { landing?: Landing } = {};
		const runSignal = background.track(runId);
		const onTurn = tree && (async (turn: Turn) => {
			if (turn.error) return;
			registry.update(runId, { state: "landing" });
			merged.landing = await land({ tree, first: replyEvent(turn), privateNames: forkSettings(pi).privateNames });
		});
		const mcp = run.model || forkSettings(pi).mcpProxy === true ? async (tool: string, args: unknown) => {
			const mainTools = await mainToolsContext();
			if (!mainTools) return { content: [{ type: "text" as const, text: "Main has not run a tool since its reload, so it cannot run this MCP call yet, so retry in a minute." }], isError: true };
			const { result, isError } = await mainTools.executeTool(tool, args, { signal: runSignal });
			return { content: result.content, details: result.details, structuredContent: result.structuredContent, isError };
		} : undefined;
		const keep = () => registry.get(runId)?.state === "lost";
		if (slots.full) {
			fs.mkdirSync(run.files, { recursive: true, mode: 0o700 });
			fs.writeFileSync(path.join(run.files, QUEUED_ENTRIES), JSON.stringify(delegate.entries ?? []), { mode: 0o600 });
			registry.update(runId, { files: run.files, queued: { message: delegate.message, resume: Boolean(delegate.resume) } });
		}
		const running = slots.run(() => (registry.get(runId)?.queued && (registry.update(runId, { queued: undefined }), fs.rmSync(path.join(run.files, QUEUED_ENTRIES), { force: true })), runDelegate(pi, ctx, { role: run.role, name, ...delegate, signal: runSignal, command, runId, model: run.model, mcp, worktree: tree?.path ?? (run.role.writes ? (run.target ?? ctx.cwd) : undefined), repo: tree?.repo, cwd: run.target, files: run.files, keep, continuable: true, onChild: (child) => background.attach(runId, child), onWarmup: (waiting) => background.view?.note(runId, waiting ? "waiting for cache" : undefined), onTurn })), runSignal);
		const onEnd = async (turn: Awaited<typeof running>) => {
			const current = registry.get(runId);
			if (!current || !isLive(current) || runSignal.aborted) return;
			const end = { ...endOf(ref, turn, merged.landing), lastRequestAt: turn.lastRequestAt, context: turn.context };
			const text = turn.error ?? replyOf(turn);
			const note = merged.landing && tree ? `[merge: ${describeLanding(merged.landing, tree)}]` : tree && (await dropIfClean(tree)) ? "[merge: worktree removed: clean]" : undefined;
			background.finish(ctx, runId, end, turn.error ?? turn.reply ?? text, note);
			pi.appendEntry("result-cap", { ref: end.ref, text });
		};
		const onFail = async (error: unknown) => {
			if (registry.get(runId)?.state === "cancelled") fs.rmSync(path.join(run.files, QUEUED_ENTRIES), { force: true });
			if (registry.get(runId)?.state === "lost" || runSignal.aborted) return;
			const removed = tree && (await dropIfClean(tree));
			background.finish(ctx, runId, { state: "failed" }, error instanceof Error ? error.message : String(error), removed ? "[merge: worktree removed: clean]" : undefined);
		};
		void running.then(onEnd, onFail).catch((error) => report(ctx, error));
	}

	const textOf = (result: AgentToolResult<unknown>) => result.content.map((block) => (block.type === "text" ? block.text : "")).join("\n");
	const forkTool = defineTool({
		name: "fork",
		label: "Fork",
		description:
			"Run a delegate on a copy of this session, so it knows everything you know and reuses the prompt cache. Give it one self-contained task. A reader (the default) only reads. A writer works in its own git worktree and its commits are rebased, tested and fast-forwarded onto the current branch. A writer can only work in its own worktree, so give each branch its own writer. With branch, and optionally base (a ref, default the current branch), the writer starts on that new branch from the base. It pushes the branch with git push, and the landing is that push: unpushed work escalates and nothing lands on the current branch. Use it for one PR per writer. target points either role at another directory. A writer whose directory is not a git checkout writes in place, and nothing lands. It returns at once and the result arrives as a message when the delegate calls reply and the work has landed. from runs on a copy of a finished fork's session instead. A session over 150000 tokens of context starts the fork cold on the same model with a summary instead of a copy. shared with tasks and model runs one cold stub that reads shared and the contents of the files in sharedFiles in a single request, then starts one child per task from that stub when it finishes, so they share its prompt cache.",
		promptSnippet: "Run a read-only or worktree-writing delegate on a copy of this session in the background",
		parameters: Type.Object({
			task: Type.Optional(Type.String({ description: "What the delegate should find out or check" })),
			role: Type.Optional(Type.Union([Type.Literal("reader"), Type.Literal("writer")], { description: "reader (default) reads only, writer commits in its own worktree" })),
			name: Type.Optional(Type.String({ pattern: "^[a-z0-9-]{1,24}$", description: "Short name for the delegate" })),
			target: Type.Optional(Type.String({ description: "Path of another directory, git checkout or worktree to read or land in, instead of this session's" })),
			base: Type.Optional(Type.String({ description: "Writer only, with branch: the ref its new branch starts from, such as origin/main. Default: the current branch" })),
			branch: Type.Optional(Type.String({ description: "Writer only: a new branch for its worktree to start on, which it pushes instead of landing on the current branch" })),
			shared: Type.Optional(Type.String({ description: "Text a cold stub on model reads once before the tasks start from copies of its session" })),
			sharedFiles: Type.Optional(Type.Array(Type.String(), { description: "With shared: paths of files, relative to this session's directory or target, whose contents go into the stub's prompt after the shared text" })),
			tasks: Type.Optional(Type.Array(Type.Object({ name: Type.String({ pattern: "^[a-z0-9-]{1,24}$" }), task: Type.String() }), { description: "With shared: one child per task, each on a copy of the stub's session" })),
			from: Type.Optional(Type.String({ pattern: "^[a-z0-9-]{1,24}$", description: "Name of a finished fork: run on a new copy of its session, at its model and effort, instead of on this session" })),
			model: Type.Optional(Type.String({ pattern: "^[A-Za-z0-9][\\w./:@-]*$", description: "Run as a cold worker on this model: provider/id (optionally :thinking) or a tier name such as sol or opus. Any model starts an empty session with no context and no prompt cache from you, so the task must be self-contained" })),
		}),
		async execute(toolCallId, params, signal, onUpdate, ctx): Promise<AgentToolResult<unknown>> {
			recordMainTools(ctx);
			if (process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can fork.");
			if (!ctx.model) throw new Error("Cannot fork without a model.");
			if (params.shared !== undefined || params.sharedFiles !== undefined || params.tasks !== undefined) {
				if (params.shared === undefined || !params.tasks?.length || params.model === undefined || params.task !== undefined || params.from !== undefined) throw new Error("shared needs tasks and model, without task or from");
				const stub = params.name ?? `stub-${randomUUID().slice(0, 6)}`;
				const names = [stub, ...params.tasks.map(({ name }) => name)];
				const repeated = names.find((name, at) => names.indexOf(name) !== at);
				if (repeated) throw new Error(`task names must be unique and differ from the stub's: ${repeated}`);
				const common = { role: params.role, target: params.target };
				const sharedDir = path.resolve(ctx.cwd, expandHome(params.target ?? "."));
				const files = (params.sharedFiles ?? []).map((file) => {
					try {
						return `File ${file}:\n${fs.readFileSync(path.resolve(sharedDir, expandHome(file)), "utf8").trimEnd()}`;
					} catch (error) {
						throw new Error(`cannot read shared file ${file}: ${error instanceof Error ? error.message : String(error)}`);
					}
				});
				const task = [params.shared, ...files, STUB_SUFFIX].join("\n\n");
				const started = await forkTool.execute(toolCallId, { ...common, name: stub, model: params.model, task }, signal, onUpdate, ctx);
				const stubId = (started.details as { runId: string }).runId;
				const failTask = ({ name, task }: { name: string; task: string }, error: unknown) => {
					const id = newRunId();
					registry.start({ id, name, role: params.role ?? "reader", background: true, state: "running", task, cwd: ctx.cwd, startedAt: Date.now() });
					background.finish(ctx, id, { state: "failed" }, error instanceof Error ? error.message : String(error));
				};
				const startTasks = async () => {
					const source = finishedRun(registry.all(), stub);
					if (source.state !== "done") throw new Error(`stub ${stub} ended ${source.state}: its task did not start`);
					const mark = path.join(source.files, FINISHED_MARK);
					const held = fs.existsSync(mark) && (fs.rmSync(mark), true);
					try {
						const children = await Promise.allSettled(params.tasks!.map((child) => forkTool.execute(toolCallId, { ...common, name: child.name, task: child.task, from: stub }, signal, onUpdate, ctx)));
						children.forEach((child, at) => child.status === "rejected" && failTask(params.tasks![at], child.reason));
					} finally {
						if (held) fs.writeFileSync(mark, "");
					}
				};
				const stopWatching = registry.onChange((run) => {
					if (run.id !== stubId || isLive(run)) return;
					stopWatching();
					void startTasks().catch((error) => params.tasks!.forEach((task) => failTask(task, error)));
				});
				return { content: [{ type: "text", text: `${textOf(started)}\ntasks ${params.tasks.map(({ name }) => name).join(", ")} start when ${stub} finishes` }], details: { name: stub, runId: stubId, tasks: params.tasks.map(({ name }) => name) } };
			}
			if (params.task === undefined) throw new Error("fork needs task, or shared with tasks");
			sweepFinished();
			if (params.from !== undefined && params.model !== undefined) throw new Error("from runs at the source's model and effort: drop model");
			const source = params.from === undefined ? undefined : finishedRun(registry.all(), params.from);
			const role: Role = ROLES[params.role ?? (source?.role as Role["name"] | undefined) ?? "reader"];
			const name = params.name ?? `fork-${randomUUID().slice(0, 6)}`;
			const targetPath = params.target ?? (source && (source.target ?? source.cwd));
			const dir = path.resolve(ctx.cwd, expandHome(targetPath ?? "."));
			if (!fs.existsSync(dir)) throw new Error(`target ${targetPath} does not exist`);
			const checkout = await checkoutOf(dir);
			const home = targetPath === undefined ? ctx.cwd : role.writes ? (checkout ?? dir) : dir;
			const target = sameDir(home, ctx.cwd) ? undefined : home;
			const entries = seedEntries(ctx.sessionManager.getBranch(), toolCallId);
			const tooLarge = !source && !params.model && (ctx.getContextUsage()?.tokens ?? 0) > WARM_FORK_MAX_TOKENS;
			const model = source ? source.model : tooLarge ? `${ctx.model.provider}/${ctx.model.id}:${pi.getThinkingLevel()}` : params.model && resolveModel(params.model);
			const runId = newRunId();
			const ref = `rc-fork-${name}-${toolCallId}`;
			const cold = tooLarge ? `fork ${name} cold on ${model} with a summary: context over ${WARM_FORK_MAX_TOKENS} tokens` : params.model && model ? coldLabel(name, params.model, model) : undefined;
			const hint = source ? undefined : cachedHint(registry.all(), role.name, target ?? ctx.cwd, (run) => savedPrice(ctx, run), freshStartCost(ctx, role, params.task, model));
			const withHint = (text: string) => (hint ? `${text}\n${hint}` : text);
			let queued = false;
			const launch = async (summary?: string, cancelled?: AbortSignal) => {
				if (cancelled?.aborted) return false;
				const files = path.join(getAgentDir(), "pi-context", randomUUID());
				if (source) copySession(source.files, files, Boolean(source.model));
				const tree = role.writes && checkout ? await createWorktree(home, path.join(getAgentDir(), "pi-context", WORKTREES), name, params).catch((error: unknown) => {
					fs.rmSync(files, { recursive: true, force: true });
					throw error;
				}) : undefined;
				if (cancelled?.aborted) {
					if (tree) await dropIfClean(tree);
					return false;
				}
				const placed = { worktree: tree?.path, branch: tree?.branch, tree };
				if (tooLarge) registry.update(runId, placed);
				else registry.start({ id: runId, name, role: role.name, ...(source && { from: source.from ?? source.name, cacheKey: cacheKeyOf(files) }), model, background: true, state: "running", task: params.task!, ...placed, target, cwd: ctx.cwd, startedAt: Date.now() });
				const message = `${worktreeLine(tree, role.writes ? home : undefined)}${summary ? `Summary of the session you fork from:\n${summary}\n\n` : ""}Task: ${params.task}`;
				const queued = slots.full;
				startRun(ctx, { id: runId, name, ref, role, tree, target, model, files }, { entries, message, resume: Boolean(source) });
				return queued;
			};
			if (tooLarge) {
				signal?.throwIfAborted();
				registry.start({ id: runId, name, role: role.name, model, background: true, state: "running", task: params.task, target, cwd: ctx.cwd, startedAt: Date.now() });
				const cancelled = background.track(runId);
				const cancelOnAbort = () => void background.cancelRun(runId);
				signal?.addEventListener("abort", cancelOnAbort, { once: true });
				const onFail = (error: unknown) => !cancelled.aborted && background.finish(ctx, runId, { state: "failed" }, error instanceof Error ? error.message : String(error));
				void summaryOf(ctx, entries).then((summary) => launch(summary, cancelled)).catch(onFail).finally(() => signal?.removeEventListener("abort", cancelOnAbort));
			} else queued = await launch();
			return { content: [{ type: "text", text: withHint(`${queued ? "queued" : "started"} ${cold ?? `fork ${name}`} (background)${queued ? ": starts when a running fork finishes" : ""}`) }], details: { name, runId, background: true } };
		},
	});
	pi.registerTool(forkTool);
	/** Restarts a lost run on its own session and worktree. */
	async function resumeRun(ctx: ExtensionToolContext, run: Run & { files: string }, callId: string) {
		background.resolveForkAsks(ctx, run.name);
		if (run.tree) await restoreWorktree(run.tree);
		const { queued } = run;
		registry.update(run.id, { state: "running", endedAt: undefined, endedBy: undefined, queued: undefined });
		const message = queued?.message ?? `${worktreeLine(run.tree)}Your session stopped before you finished. Continue the task from where you left off, and end by calling reply.`;
		const delegate = queued ? { entries: JSON.parse(readText(path.join(run.files, QUEUED_ENTRIES)) ?? "[]") as SessionEntry[], message, resume: queued.resume } : { message, resume: true };
		startRun(ctx, { id: run.id, name: run.name, ref: `rc-fork-${run.name}-${callId}`, role: ROLES[run.role as Role["name"]], tree: run.tree, target: run.target, model: run.model, files: run.files }, delegate);
	}

	/** Gives a finished run a new task on its own session, model and role, in the background. */
	async function continueRun(ctx: ExtensionToolContext, name: string, task: string, toolCallId: string) {
		sweepFinished();
		const run = finishedRun(registry.all(), name);
		background.resolveForkAsks(ctx, run.name);
		const tree = run.tree && (await resumeWorktree(run.tree, path.join(getAgentDir(), "pi-context", WORKTREES), run.name));
		registry.update(run.id, { state: "running", task, background: true, tree, worktree: tree?.path, branch: tree?.branch, startedAt: Date.now(), endedAt: undefined, endedBy: undefined, outcome: undefined, notify: undefined });
		const message = `${worktreeLine(tree)}Task: ${task}`;
		startRun(ctx, { id: run.id, name: run.name, ref: `rc-fork-${run.name}-${toolCallId}`, role: ROLES[run.role as Role["name"]], tree, target: run.target ?? run.cwd, model: run.model, files: run.files }, { message, resume: true });
		return { content: [{ type: "text" as const, text: `continued fork ${run.name} (background)` }], details: { name: run.name, runId: run.id, background: true } };
	}

	pi.registerTool({
		name: "fork_cancel",
		label: "Fork cancel",
		description: "Stop a live background fork by name. A writer's worktree stays where it is.",
		promptSnippet: "Stop a live background fork",
		parameters: Type.Object({ name: Type.String({ description: "Name of the background fork" }) }),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			recordMainTools(ctx);
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
			recordMainTools(ctx);
			if (process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can resume a fork.");
			if (params.task !== undefined) return continueRun(ctx, params.name, params.task, toolCallId);
			const resumable = registry.all().filter(canResume);
			const run = resumable.filter((candidate) => candidate.name === params.name).at(-1);
			if (!run?.files) throw new Error(`no lost fork ${params.name} to resume. Resumable: ${resumable.map((candidate) => candidate.name).join(", ") || "none"}`);
			await resumeRun(ctx, { ...run, files: run.files }, toolCallId);
			return { content: [{ type: "text", text: `resumed fork ${run.name} (background)` }], details: { name: run.name, runId: run.id, background: true } };
		},
	});
	pi.registerTool({
		name: "fork_steer",
		label: "Fork steer",
		description: "Send a message to a live background fork. It reaches the fork after its current tool calls, before its next model call. A finished fork instead resumes in the background with the message as its new task.",
		promptSnippet: "Steer a live background fork, or resume a finished one",
		parameters: Type.Object({ name: Type.String({ description: "Name of the background fork" }), message: Type.String({ description: "What the fork should do differently or also do" }) }),
		async execute(toolCallId, params, _signal, _onUpdate, ctx) {
			recordMainTools(ctx);
			if (process.env.PI_CONTEXT_CHILD) throw new Error("Only the top-level session can steer a fork.");
			const isLiveFork = registry.live().some((run) => run.background && run.name === params.name);
			if (!isLiveFork && registry.all().some((run) => run.name === params.name && canContinue(run))) return continueRun(ctx, params.name, params.message, toolCallId);
			await background.steer(params.name, params.message);
			background.resolveForkAsks(ctx, params.name);
			return { content: [{ type: "text", text: `steered fork ${params.name}` }], details: { name: params.name } };
		},
	});

	pi.on("session_shutdown", () => recordMainTools(undefined));
	pi.on("session_start", async (event, ctx) => {
		if (process.env.PI_CONTEXT_CHILD || event.reason !== "reload" || !reloadRequested()) return;
		const resumed: string[] = [];
		for (const run of registry.all().filter((candidate) => candidate.endedBy === "reload" && canResume(candidate))) {
			await resumeRun(ctx as ExtensionToolContext, { ...run, files: run.files! }, `reload-${run.id}`);
			resumed.push(run.name);
		}
		if (resumed.length) pi.sendMessage({ customType: RESULTS_TYPE, content: `resumed forks: ${resumed.join(", ")}`, display: true }, { deliverAs: "nextTurn" });
	});
}
