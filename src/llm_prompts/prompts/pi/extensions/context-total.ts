// Shows live context size and cost for the session and its agents.
// Commands: /context-total [footer on|off]
// Config: context-total.json keys footer, intervalSeconds
import fs from "node:fs";
import path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";

const BYTES_PER_TOKEN = 4;
const MESSAGE_LINE_START = '{"type":"message"';
const SPAWN_TOOLS = new Set(["delegate_agent", "continue_agent", "agent_delegate", "agent_continue"]);
const CONFIG_FILE = "context-total.json";
const STATUS_KEY = "context-total";
const VARIABLE_EVENT = "zentui:variable";
const CAPABILITY_EVENT = "zentui:variable-capability";
const CONTEXT_VARIABLE = "llm-prompts/context-total:ctx";
const COST_VARIABLE = "llm-prompts/context-total:cost";
const DEFAULT_INTERVAL_SECONDS = 5;
const MIN_INTERVAL_SECONDS = 2;
const MS_PER_SECOND = 1000;
const MAILBOX_DIR = ["pi-herdsman", "runtime", "mailboxes-v5"];
const RESULT_TYPE = "pi-herdsman-agent-result";
const INTERESTING_LINE = new RegExp(
	`"usage":|"role":"assistant"|"type":"compaction"|"type":"model_change"|${RESULT_TYPE}|"toolName":"(?:${[...SPAWN_TOOLS].join("|")})"`,
);

type Usage = { input: number; output: number; cacheRead: number; cacheWrite: number; totalTokens?: number; cost?: { total?: number } };
export type UsageTotals = { tokens: number; cost: number };
type ContextUsage = { tokens: number | null; contextWindow: number; percent: number | null };
type Details = Record<string, unknown>;
type Entry = {
	type?: string;
	provider?: string;
	modelId?: string;
	customType?: string;
	details?: Details;
	usage?: Usage;
	message?: { role?: string; provider?: string; model?: string; stopReason?: string; usage?: Usage; toolName?: string; isError?: boolean; customType?: string; details?: Details };
};

export type Child = {
	sessionId: string;
	sessionPath: string;
	label: string;
	definition: string;
	requestId: string;
	done: boolean;
	usage?: ContextUsage;
};

export type Scan = {
	ownerId: string;
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

export type NodeState = "live" | "finished" | "lost";

export type Node = {
	sessionId: string;
	label: string;
	definition: string;
	depth: number;
	state: NodeState;
	tokens: number | null;
	contextWindow?: number;
	percent: number | null;
};

export type Sample = { nodes: Node[]; partial: boolean; session: UsageTotals; tree: UsageTotals };

export type SampleOptions = {
	mailboxIds?: Set<string>;
	windowOf?: (provider: string, modelId: string) => number | undefined;
};

export function createScan(ownerId: string): Scan {
	return { ownerId, offset: 0, usageTokens: 0, trailingBytes: 0, usage: { tokens: 0, cost: 0 }, compacted: false, partial: false, children: new Map() };
}

function resetScan(scan: Scan): void {
	Object.assign(scan, createScan(scan.ownerId), { usage: { tokens: scan.usage.tokens, cost: 0 } });
}

function validUsage(message: NonNullable<Entry["message"]>): number {
	if (message.role !== "assistant" || message.stopReason === "aborted" || message.stopReason === "error" || !message.usage) return 0;
	const { usage } = message;
	return usage.totalTokens || usage.input + usage.output + usage.cacheRead + usage.cacheWrite;
}

function recordSpawn(scan: Scan, details: Details): void {
	const sessionId = String(details.session_id);
	scan.children.set(sessionId, {
		sessionId,
		sessionPath: String(details.session_path),
		label: String(details.agent),
		definition: String(details.definition),
		requestId: String(details.request_id),
		done: false,
	});
}

function recordResult(scan: Scan, details: Details): void {
	const child = scan.children.get(String(details.piSessionId));
	if (child && child.requestId === details.requestId) {
		child.done = true;
		child.usage = details.contextUsage as ContextUsage;
	}
}

function addUsage(scan: Scan, usage: Usage | undefined): void {
	if (!usage) return;
	scan.usage.cost += usage.cost?.total ?? 0;
}

export function scanUsage(scan: Scan): UsageTotals {
	return { ...scan.usage };
}

export function feedEntry(scan: Scan, entry: Entry, size: number): void {
	addUsage(scan, entry.type === "message" ? entry.message?.usage : entry.usage);
	if (entry.type === "model_change") {
		scan.provider = entry.provider;
		scan.modelId = entry.modelId;
	}
	const customType = (entry.message ?? entry).customType;
	const details = entry.message?.details ?? entry.details;
	if (customType === RESULT_TYPE && details?.ownerSessionId === scan.ownerId) recordResult(scan, details);
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
		const { toolName, isError } = entry.message;
		if (toolName && SPAWN_TOOLS.has(toolName) && !isError && details?.ok === true && details.owner_session_id === scan.ownerId) {
			recordSpawn(scan, details);
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

export async function readMailboxIds(agentDir: string): Promise<Set<string> | undefined> {
	const root = path.join(agentDir, ...MAILBOX_DIR);
	let names: string[];
	try {
		names = await fs.promises.readdir(root);
	} catch {
		return undefined;
	}
	const ids = new Set<string>();
	for (const name of names) {
		try {
			const state = JSON.parse(await fs.promises.readFile(path.join(root, name, "state.json"), "utf8")) as { piSessionId?: string };
			if (state.piSessionId) ids.add(state.piSessionId);
		} catch {
			// a mailbox being written or removed is skipped
		}
	}
	return ids;
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

function finishedNode(child: Child, depth: number): Node {
	const { usage } = child;
	return {
		sessionId: child.sessionId,
		label: child.label,
		definition: child.definition,
		depth,
		state: "finished",
		tokens: usage?.tokens ?? null,
		contextWindow: usage?.contextWindow,
		percent: usage?.percent ?? null,
	};
}

export async function sampleChildren(root: Scan, scans: Map<string, Scan>, options: SampleOptions = {}): Promise<Sample> {
	const nodes: Node[] = [];
	const visited = new Set([root.ownerId]);
	const touched: Scan[] = [root];
	const walk = async (scan: Scan, depth: number, listed: boolean): Promise<void> => {
		for (const child of listChildren(scan)) {
			if (visited.has(child.sessionId)) continue;
			visited.add(child.sessionId);
			let childScan = scans.get(child.sessionId);
			if (!childScan) scans.set(child.sessionId, (childScan = createScan(child.sessionId)));
			touched.push(childScan);
			await readIfPresent(childScan, child.sessionPath);
			if (child.done) {
				if (listed) nodes.push(finishedNode(child, depth));
				await walk(childScan, depth + 1, false);
				continue;
			}
			const tokens = scanTokens(childScan);
			const contextWindow = childScan.provider && childScan.modelId ? options.windowOf?.(childScan.provider, childScan.modelId) : undefined;
			const live = !options.mailboxIds || options.mailboxIds.has(child.sessionId);
			if (listed) {
				nodes.push({
					sessionId: child.sessionId,
					label: child.label,
					definition: child.definition,
					depth,
					state: live ? "live" : "lost",
					tokens,
					contextWindow,
					percent: percentOf(tokens, contextWindow),
				});
			}
			await walk(childScan, depth + 1, listed && live);
		}
	};
	await walk(root, 0, true);
	const tree = touched.reduce<UsageTotals>(
		(sum, scan) => ({ tokens: sum.tokens + scan.usage.tokens, cost: sum.cost + scan.usage.cost }),
		{ tokens: 0, cost: 0 },
	);
	return { nodes, partial: touched.some((scan) => scan.partial), session: scanUsage(root), tree };
}

const TOKENS_PER_K = 1000;
const TOKENS_PER_M = 1_000_000;
const STATS_LINE = "Cumulative tokens and cost: /herdsman stats";

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
	return `${indent}${node.label} (${node.definition})  ${usage}${node.state === "lost" ? " [lost]" : ""}`;
}

export function formatReport(lead: LeadUsage, sample: Sample): string {
	const { tokens, sessions, unknown } = liveTotal(lead, sample);
	const ended = sample.nodes.filter((node) => node.state !== "live");
	return [
		`Live context: ${formatTokens(tokens)}${unknown ? "+" : ""} across ${sessions} sessions${sample.partial ? " (partial)" : ""}`,
		"Running",
		`  lead  ${lead ? formatUsage(lead.tokens, lead.contextWindow, lead.percent) : "unknown"}`,
		...sample.nodes.filter((node) => node.state === "live").map((node) => nodeLine(node, "  ".repeat(node.depth + 1))),
		...(ended.length ? ["Finished (last known)", ...ended.map((node) => nodeLine(node, "  "))] : []),
		`Tree cumulative: ${formatTokens(sample.tree.tokens)} tokens, ${formatDollars(sample.tree.cost)}`,
		STATS_LINE,
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
		const sampled = await sampleChildren(root, scans, {
			mailboxIds: await readMailboxIds(agentDir),
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
