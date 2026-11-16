// Shows live context size and cost for the session and its forks.
// Commands: /context-total [footer on|off]
// Config: context-total.json keys footer, intervalSeconds
import fs from "node:fs";
import path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { forkRegistry, isLive, type Run } from "./pi-context/registry.ts";

const BYTES_PER_TOKEN = 4;
const MESSAGE_LINE_START = '{"type":"message"';
const CONFIG_FILE = "context-total.json";
const STATUS_KEY = "context-total";
const VARIABLE_EVENT = "zentui:variable";
const CAPABILITY_EVENT = "zentui:variable-capability";
const CONTEXT_VARIABLE = "llm-prompts/context-total:ctx";
const COST_VARIABLE = "llm-prompts/context-total:cost";
const DEFAULT_INTERVAL_SECONDS = 5;
const MIN_INTERVAL_SECONDS = 2;
const MS_PER_SECOND = 1000;
const INTERESTING_LINE = /"usage":|"role":"assistant"|"type":"compaction"|"type":"model_change"/;

type Usage = { input: number; output: number; cacheRead: number; cacheWrite: number; totalTokens?: number; cost?: { total?: number } };
export type UsageTotals = { tokens: number; cost: number };
type ContextUsage = { tokens: number | null; contextWindow: number; percent: number | null };
type Entry = {
	type?: string;
	timestamp?: string;
	provider?: string;
	modelId?: string;
	usage?: Usage;
	message?: { role?: string; provider?: string; model?: string; stopReason?: string; usage?: Usage };
};

export type Child = {
	sessionId: string;
	sessionPath: string;
	label: string;
	definition: string;
	done: boolean;
	usage?: ContextUsage;
	/** Cost before this time belongs to another session, as in a fork's seed. */
	since?: number;
};

export type Scan = {
	ownerId: string;
	since?: number;
	offset: number;
	usageTokens: number;
	trailingBytes: number;
	usage: UsageTotals;
	compacted: boolean;
	partial: boolean;
	children: Map<string, Child>;
	provider?: string;
	modelId?: string;
};

export type LeadTracker = { sessionId?: string; index: number; scan: Scan };

export type NodeState = "live" | "finished";

export type Node = {
	sessionId: string;
	label: string;
	definition: string;
	state: NodeState;
	tokens: number | null;
	contextWindow?: number;
	percent: number | null;
};

export type Sample = { nodes: Node[]; partial: boolean; session: UsageTotals; tree: UsageTotals };

export type SampleOptions = {
	windowOf?: (provider: string, modelId: string) => number | undefined;
};

export function createScan(ownerId: string, since?: number): Scan {
	return { ownerId, since, offset: 0, usageTokens: 0, trailingBytes: 0, usage: { tokens: 0, cost: 0 }, compacted: false, partial: false, children: new Map() };
}

function resetScan(scan: Scan): void {
	Object.assign(scan, createScan(scan.ownerId, scan.since), { usage: { tokens: scan.usage.tokens, cost: 0 } });
}

function validUsage(message: NonNullable<Entry["message"]>): number {
	if (message.role !== "assistant" || message.stopReason === "aborted" || message.stopReason === "error" || !message.usage) return 0;
	const { usage } = message;
	return usage.totalTokens || usage.input + usage.output + usage.cacheRead + usage.cacheWrite;
}

function addUsage(scan: Scan, usage: Usage | undefined): void {
	if (!usage) return;
	scan.usage.cost += usage.cost?.total ?? 0;
}

export function scanUsage(scan: Scan): UsageTotals {
	return { ...scan.usage };
}

export function feedEntry(scan: Scan, entry: Entry, size: number): void {
	if (!scan.since || !entry.timestamp || Date.parse(entry.timestamp) >= scan.since) addUsage(scan, entry.type === "message" ? entry.message?.usage : entry.usage);
	if (entry.type === "model_change") {
		scan.provider = entry.provider;
		scan.modelId = entry.modelId;
	}
	if (entry.type === "compaction") {
		scan.compacted = true;
		scan.usageTokens = 0;
		scan.trailingBytes = 0;
	} else if (entry.type === "message" && entry.message) {
		const tokens = validUsage(entry.message);
		if (tokens > 0) {
			scan.usageTokens = tokens;
			scan.usage.tokens = Math.max(scan.usage.tokens, tokens);
			scan.trailingBytes = 0;
			scan.compacted = false;
			scan.provider = entry.message.provider ?? scan.provider;
			scan.modelId = entry.message.model ?? scan.modelId;
		} else {
			scan.trailingBytes += size;
		}
	}
}

export function listChildren(scan: Scan): Child[] {
	return [...scan.children.values()].map((child) => ({ ...child }));
}

export function feedLine(scan: Scan, line: string): void {
	if (!INTERESTING_LINE.test(line)) {
		if (line.startsWith(MESSAGE_LINE_START)) scan.trailingBytes += line.length;
		return;
	}
	try {
		feedEntry(scan, JSON.parse(line) as Entry, line.length);
	} catch {
		scan.partial = true;
	}
}

export function scanTokens(scan: Scan): number | null {
	return scan.compacted || scan.offset === 0 ? null : scan.usageTokens + Math.ceil(scan.trailingBytes / BYTES_PER_TOKEN);
}

export async function readNew(scan: Scan, file: string): Promise<void> {
	const { size } = await fs.promises.stat(file);
	if (size < scan.offset) resetScan(scan);
	if (size === scan.offset) return;
	const handle = await fs.promises.open(file, "r");
	try {
		const buffer = Buffer.alloc(size - scan.offset);
		await handle.read(buffer, 0, buffer.length, scan.offset);
		const end = buffer.lastIndexOf(10) + 1;
		scan.offset += end;
		for (const line of buffer.subarray(0, end).toString("utf8").split("\n")) feedLine(scan, line);
	} finally {
		await handle.close();
	}
}

export function createLeadTracker(): LeadTracker {
	return { index: 0, scan: createScan("") };
}

export function syncLead(tracker: LeadTracker, sessionId: string, entries: Entry[]): Scan {
	if (tracker.sessionId !== sessionId || entries.length < tracker.index) {
		tracker.sessionId = sessionId;
		tracker.index = 0;
		tracker.scan = createScan(sessionId);
	}
	for (const entry of entries.slice(tracker.index)) feedEntry(tracker.scan, entry, 0);
	tracker.index = entries.length;
	return tracker.scan;
}

function percentOf(tokens: number | null, contextWindow: number | undefined): number | null {
	return tokens !== null && contextWindow ? (tokens / contextWindow) * 100 : null;
}

async function readIfPresent(scan: Scan, file: string): Promise<void> {
	try {
		await readNew(scan, file);
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code !== "ENOENT") scan.partial = true;
	}
}

function finishedNode(child: Child): Node {
	const { usage } = child;
	return {
		sessionId: child.sessionId,
		label: child.label,
		definition: child.definition,
		state: "finished",
		tokens: usage?.tokens ?? null,
		contextWindow: usage?.contextWindow,
		percent: usage?.percent ?? null,
	};
}

export async function sampleChildren(root: Scan, scans: Map<string, Scan>, options: SampleOptions = {}): Promise<Sample> {
	const nodes: Node[] = [];
	const touched: Scan[] = [root];
	for (const child of listChildren(root)) {
		let childScan = scans.get(child.sessionId);
		if (!childScan) scans.set(child.sessionId, (childScan = createScan(child.sessionId, child.since)));
		touched.push(childScan);
		await readIfPresent(childScan, child.sessionPath);
		if (child.done) {
			nodes.push(finishedNode(child));
			continue;
		}
		const tokens = scanTokens(childScan);
		const contextWindow = childScan.provider && childScan.modelId ? options.windowOf?.(childScan.provider, childScan.modelId) : undefined;
		nodes.push({ sessionId: child.sessionId, label: child.label, definition: child.definition, state: "live", tokens, contextWindow, percent: percentOf(tokens, contextWindow) });
	}
	const tree = touched.reduce<UsageTotals>(
		(sum, scan) => ({ tokens: sum.tokens + scan.usage.tokens, cost: sum.cost + scan.usage.cost }),
		{ tokens: 0, cost: 0 },
	);
	return { nodes, partial: touched.some((scan) => scan.partial), session: scanUsage(root), tree };
}

function forkSessionFile({ files = "", model }: Run): string {
	const seed = path.join(files, "seed.jsonl");
	if (!model) return seed;
	const sessions = path.join(files, "sessions");
	const name = fs.existsSync(sessions) ? fs.readdirSync(sessions).find((file) => file.endsWith(".jsonl")) : undefined;
	return name ? path.join(sessions, name) : seed;
}

/** Records each fork run as a child of the root, a finished one with its last sampled context. */
export function addForkChildren(root: Scan, scans: Map<string, Scan>, runs: Run[]): void {
	for (const run of runs) {
		const done = !isLive(run);
		const scan = scans.get(run.id);
		root.children.set(run.id, {
			sessionId: run.id,
			sessionPath: forkSessionFile(run),
			label: run.name,
			definition: run.role,
			done,
			usage: done ? { tokens: scan ? scanTokens(scan) : null, contextWindow: 0, percent: null } : undefined,
			since: run.startedAt,
		});
	}
}

const TOKENS_PER_K = 1000;
const TOKENS_PER_M = 1_000_000;

type LeadUsage = Pick<ContextUsage, "tokens" | "contextWindow" | "percent"> | undefined;

function formatTokens(tokens: number): string {
	if (tokens < TOKENS_PER_K) return String(tokens);
	return tokens < TOKENS_PER_M ? `${Math.round(tokens / TOKENS_PER_K)}k` : `${(tokens / TOKENS_PER_M).toFixed(1)}M`;
}

function formatDollars(cost: number): string {
	return `$${cost.toFixed(2)}`;
}

function formatUsage(tokens: number | null, contextWindow: number | undefined, percent: number | null): string {
	if (tokens === null) return "unknown";
	if (!contextWindow || percent === null) return formatTokens(tokens);
	return `${formatTokens(tokens)} / ${formatTokens(contextWindow)} (${Math.round(percent)}%)`;
}

function sumTokens(values: (number | null)[]): { tokens: number; unknown: boolean } {
	return { tokens: values.reduce<number>((sum, tokens) => sum + (tokens ?? 0), 0), unknown: values.includes(null) };
}

function liveNodeTokens(sample: Sample): (number | null)[] {
	return sample.nodes.filter((node) => node.state === "live").map((node) => node.tokens);
}

function liveTotal(lead: LeadUsage, sample: Sample): { tokens: number; sessions: number; unknown: boolean } {
	const live = [lead?.tokens ?? null, ...liveNodeTokens(sample)];
	return { ...sumTokens(live), sessions: live.length };
}

export function formatContext(sample: Sample): string {
	const { tokens, unknown } = sumTokens(liveNodeTokens(sample));
	return `agents ${formatTokens(tokens)}${unknown ? "+" : ""} \u00b7 tree ${formatTokens(sample.tree.tokens)}`;
}

export function formatCost(sample: Sample): string {
	return `${formatDollars(sample.session.cost)}/${formatDollars(sample.tree.cost)}`;
}

export function formatFooter(sample: Sample): string {
	return `${formatContext(sample)} ${formatCost(sample)}${sample.partial ? " partial" : ""}`;
}

type EventSource = Pick<ExtensionAPI, "events">;
type StatusUi = Pick<ExtensionContext["ui"], "setStatus">;

function variableActive({ events }: EventSource, key: string): boolean {
	const probe = { supported: false, active: false, key };
	events.emit(CAPABILITY_EVENT, probe);
	return probe.active;
}

export function publishFooter(pi: EventSource, ui: StatusUi, sample: Sample): void {
	const context = `${formatContext(sample)}${sample.partial ? " partial" : ""}`;
	const cost = formatCost(sample);
	if (variableActive(pi, CONTEXT_VARIABLE) && variableActive(pi, COST_VARIABLE)) {
		pi.events.emit(VARIABLE_EVENT, { key: CONTEXT_VARIABLE, text: context });
		pi.events.emit(VARIABLE_EVENT, { key: COST_VARIABLE, text: cost });
		ui.setStatus(STATUS_KEY, undefined);
	} else {
		ui.setStatus(STATUS_KEY, formatFooter(sample));
	}
}

export function clearFooter(pi: EventSource, ui: StatusUi): void {
	for (const key of [CONTEXT_VARIABLE, COST_VARIABLE]) pi.events.emit(VARIABLE_EVENT, { key, text: undefined });
	ui.setStatus(STATUS_KEY, undefined);
}

function nodeLine(node: Node, indent: string): string {
	const usage = formatUsage(node.tokens, node.contextWindow, node.percent);
	return `${indent}${node.label} (${node.definition})  ${usage}`;
}

export function formatReport(lead: LeadUsage, sample: Sample): string {
	const { tokens, sessions, unknown } = liveTotal(lead, sample);
	const ended = sample.nodes.filter((node) => node.state !== "live");
	return [
		`Live context: ${formatTokens(tokens)}${unknown ? "+" : ""} across ${sessions} sessions${sample.partial ? " (partial)" : ""}`,
		"Running",
		`  lead  ${lead ? formatUsage(lead.tokens, lead.contextWindow, lead.percent) : "unknown"}`,
		...sample.nodes.filter((node) => node.state === "live").map((node) => nodeLine(node, "  ")),
		...(ended.length ? ["Finished (last known)", ...ended.map((node) => nodeLine(node, "  "))] : []),
		`Tree cumulative: ${formatTokens(sample.tree.tokens)} tokens, ${formatDollars(sample.tree.cost)}`,
	].join("\n");
}

function readJson(file: string): Record<string, unknown> {
	try {
		return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
	} catch {
		return {};
	}
}

export function readConfig(file: string): { footer: boolean; intervalSeconds: number } {
	const config = readJson(file);
	const interval = typeof config.intervalSeconds === "number" ? config.intervalSeconds : DEFAULT_INTERVAL_SECONDS;
	return { footer: config.footer === true, intervalSeconds: Math.max(MIN_INTERVAL_SECONDS, interval) };
}

export function writeFooterSetting(file: string, footer: boolean): void {
	fs.writeFileSync(file, `${JSON.stringify({ ...readJson(file), footer }, null, 2)}\n`);
}

export default function (pi: ExtensionAPI) {
	const agentDir = getAgentDir();
	const configPath = path.join(agentDir, CONFIG_FILE);
	const tracker = createLeadTracker();
	const scans = new Map<string, Scan>();
	let timer: ReturnType<typeof setInterval> | undefined;
	let sampling = false;

	async function sample(ctx: ExtensionContext): Promise<{ lead: LeadUsage; sampled: Sample }> {
		const root = syncLead(tracker, ctx.sessionManager.getSessionId(), ctx.sessionManager.getEntries() as Entry[]);
		addForkChildren(root, scans, forkRegistry()?.all() ?? []);
		const sampled = await sampleChildren(root, scans, {
			windowOf: (provider, modelId) => ctx.modelRegistry.find(provider, modelId)?.contextWindow,
		});
		return { lead: ctx.getContextUsage(), sampled };
	}

	function stopSampler(): void {
		clearInterval(timer);
		timer = undefined;
	}

	function startSampler(ctx: ExtensionContext): void {
		stopSampler();
		const tick = async (): Promise<void> => {
			if (sampling) return;
			sampling = true;
			try {
				const { sampled } = await sample(ctx);
				publishFooter(pi, ctx.ui, sampled);
			} catch {
				stopSampler();
			} finally {
				sampling = false;
			}
		};
		timer = setInterval(tick, readConfig(configPath).intervalSeconds * MS_PER_SECOND);
		timer.unref();
		void tick();
	}

	async function setFooter(ctx: ExtensionCommandContext, value: string): Promise<void> {
		if (value !== "on" && value !== "off") {
			ctx.ui.notify("Usage: /context-total [footer on|off]", "warning");
			return;
		}
		writeFooterSetting(configPath, value === "on");
		if (value === "on") {
			startSampler(ctx);
		} else {
			stopSampler();
			clearFooter(pi, ctx.ui);
		}
		ctx.ui.notify(`context-total footer ${value}`, "info");
	}

	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		scans.clear();
		if (readConfig(configPath).footer) startSampler(ctx);
	});
	pi.on("session_shutdown", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		stopSampler();
		clearFooter(pi, ctx.ui);
	});
	pi.registerCommand("context-total", {
		description: "Live context total of this session and its running agents. `footer on|off` toggles the status line.",
		handler: async (args, ctx) => {
			if (ctx.mode !== "tui") return;
			const [word, value = ""] = args.trim().split(/\s+/);
			if (word === "footer") return setFooter(ctx, value);
			if (word) {
				ctx.ui.notify("Usage: /context-total [footer on|off]", "warning");
				return;
			}
			const { lead, sampled } = await sample(ctx);
			ctx.ui.notify(formatReport(lead, sampled), "info");
		},
	});
}
