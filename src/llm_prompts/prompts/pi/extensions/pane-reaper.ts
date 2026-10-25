// Closes finished agent panes in Herdr, reports merged worktrees, and kills orphaned processes left by dead agent panes, all within the current workspace.
// Commands: /pane-reaper on|off|close <pane-id>
// Config: pane-reaper.json keys enabled, graceSeconds, intervalSeconds
// Env: HERDR_ENV (1 when running inside Herdr)
// Env: PI_HERDSMAN_MAILBOX (set for managed agents, which never run the periodic check)
// Env: PI_SUBAGENT_CHILD (set for subagents, which never run the periodic check)
// Env: PI_SESSION_ID (own session id, kept out of the sweep)
// Env: PANE_REAPER_DRY_RUN (set to report orphaned processes without killing them)
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";

const execFileAsync = promisify(execFile);
const KNOWN_STATE_VERSION = 5;
const MAILBOX_DIR = path.join("pi-herdsman", "runtime", `mailboxes-v${KNOWN_STATE_VERSION}`);
const CONFIG_FILE = "pane-reaper.json";
const USAGE = "Usage: /pane-reaper [on|off|close <pane-id>]";
const NO_HERDR_WARNING = "pi is not running inside Herdr. Delegation and the herdsman agent tools need Herdr, so start pi from a Herdr pane.";
const MS_PER_SECOND = 1000;
const MS_PER_HOUR = 60 * 60 * MS_PER_SECOND;
const FRESH_HOURS = 24;
const HERDR_TIMEOUT_MS = 5000;
const DEFAULT_GRACE_SECONDS = 900;
const DEFAULT_INTERVAL_SECONDS = 60;
const MIN_INTERVAL_SECONDS = 10;
const PS_TIMEOUT_MS = 5000;
const PS_FIELDS = "pid=,uid=,ppid=,pgid=,stat=,%cpu=,time=,lstart=,command=";
const DRY_RUN_VARIABLE = "PANE_REAPER_DRY_RUN";
const INIT_PID = 1;
const COMMAND_PREVIEW_LENGTH = 80;
const SECONDS_PER_MINUTE = 60;

type Pane = {
	pane_id: string;
	tab_id: string;
	workspace_id?: string;
	cwd?: string;
	foreground_cwd?: string;
	agent_status?: string;
	display_agent?: string;
	agent_session?: { value?: string };
	tokens?: Record<string, string>;
};
type State = { version: number; ownerSessionId: string; paneId: string; activeRequestId?: string; completedRequestId?: string };
export type Candidate = { paneId: string; tabId: string; label: string; reason: string; closeArgs: string[] };
export type SweepOptions = { now: number; graceSeconds: number; selfSessionId: string; workspaceId: string };
export type SweepResult = { closed: Candidate[]; asked: Candidate[] };
export type Worktree = { path: string; branch: string; reason: string };
export type WorktreeResult = { candidates: Worktree[]; kept: Worktree[] };
type Checkout = { path: string; head: string; branch: string };
type Workspace = { workspace_id: string; worktree?: { checkout_path?: string } };
type Classified = { safe: Candidate[]; flagged: Candidate[] };

const READY_STATUSES = new Set(["idle", "done"]);
const SESSION_ID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;
const SAFE_REASON = "finished and idle, owner session is gone";
const CLOSE_FAILED_REASON = "closing it failed";
const CANDIDATE_REASON = "merged into main and clean";
const NO_COMMITS_REASON = "branch has no commits of its own";
const BRANCH_PREFIX = "refs/heads/";
const MAIN_REFS = ["main", "master"].flatMap((name) => [`${BRANCH_PREFIX}${name}`, `refs/remotes/origin/${name}`]);
const GITHUB_HOST = "github.com";
const SCP_REMOTE = /^(?:[^@/:]+@)?([^:/]+):(?!\/\/)/;

async function herdr(args: string[]): Promise<string> {
	return (await execFileAsync("herdr", args, { timeout: HERDR_TIMEOUT_MS })).stdout;
}

async function git(cwd: string, args: string[]): Promise<string> {
	return (await execFileAsync("git", args, { cwd, timeout: HERDR_TIMEOUT_MS })).stdout;
}

async function listPanes(): Promise<Pane[]> {
	return (JSON.parse(await herdr(["pane", "list"])) as { result: { panes: Pane[] } }).result.panes;
}

export async function currentWorkspaceId(): Promise<string | undefined> {
	try {
		return (JSON.parse(await herdr(["pane", "current", "--current"])) as { result: { pane: { workspace_id?: string } } }).result.pane.workspace_id;
	} catch {
		return undefined;
	}
}

async function listWorkspaces(): Promise<Workspace[]> {
	return (JSON.parse(await herdr(["workspace", "list"])) as { result: { workspaces: Workspace[] } }).result.workspaces;
}

function readStates(): Map<string, State> | undefined {
	const root = path.join(getAgentDir(), MAILBOX_DIR);
	const states = new Map<string, State>();
	try {
		for (const name of fs.readdirSync(root)) {
			const state = JSON.parse(fs.readFileSync(path.join(root, name, "state.json"), "utf8")) as State;
			if (state.version !== KNOWN_STATE_VERSION) return undefined;
			states.set(state.paneId, state);
		}
	} catch {
		return undefined;
	}
	return states;
}

function liveSessionIds(panes: Pane[], selfSessionId: string): Set<string> {
	const ids = new Set([selfSessionId]);
	for (const pane of panes) for (const id of pane.agent_session?.value?.match(SESSION_ID) ?? []) ids.add(id);
	return ids;
}

function ageMs(pane: Pane, now: number): number {
	const started = Number(pane.tokens?.started);
	return Number.isFinite(started) ? now - started : Number.POSITIVE_INFINITY;
}

function unsafeReason(pane: Pane, state: State | undefined): string | undefined {
	if (!state) return "managed pane has no herdsman state file";
	if (!READY_STATUSES.has(pane.agent_status ?? "")) return `pane is ${pane.agent_status ?? "in an unknown state"}`;
	if (state.activeRequestId || !state.completedRequestId) return "task has not finished";
	if (pane.tokens?.request !== state.completedRequestId) return "pane has a newer request than the finished one";
	return undefined;
}

function closeArgsFor(pane: Pane, panes: Pane[]): string[] {
	const aloneInTab = panes.every((other) => other === pane || other.tab_id !== pane.tab_id);
	return aloneInTab ? ["tab", "close", pane.tab_id] : ["pane", "close", pane.pane_id];
}

async function classify(options: SweepOptions): Promise<Classified> {
	const classified: Classified = { safe: [], flagged: [] };
	const states = readStates();
	if (!states) return classified;
	const panes = await listPanes();
	const live = liveSessionIds(panes, options.selfSessionId);
	const graceMs = options.graceSeconds * MS_PER_SECOND;
	for (const pane of panes) {
		const state = states.get(pane.pane_id);
		if (pane.workspace_id !== options.workspaceId || pane.tokens?.managed !== "1" || (state && live.has(state.ownerSessionId)) || ageMs(pane, options.now) < graceMs) continue;
		const reason = unsafeReason(pane, state);
		const candidate = {
			paneId: pane.pane_id,
			tabId: pane.tab_id,
			label: pane.display_agent ?? pane.pane_id,
			reason: reason ?? SAFE_REASON,
			closeArgs: closeArgsFor(pane, panes),
		};
		(reason ? classified.flagged : classified.safe).push(candidate);
	}
	return classified;
}

async function close(candidate: Candidate): Promise<boolean> {
	try {
		await herdr(candidate.closeArgs);
	} catch {
		return false;
	}
	return true;
}

export async function sweep(options: SweepOptions): Promise<SweepResult> {
	const { safe, flagged } = await classify(options);
	const result: SweepResult = { closed: [], asked: flagged };
	for (const candidate of safe) {
		if (await close(candidate)) result.closed.push(candidate);
		else result.asked.push({ ...candidate, reason: CLOSE_FAILED_REASON });
	}
	return result;
}

export async function closeFlagged(options: SweepOptions, paneId: string): Promise<Candidate | undefined> {
	const candidate = (await classify(options)).flagged.find((flagged) => flagged.paneId === paneId);
	return candidate && (await close(candidate)) ? candidate : undefined;
}

function parseCheckouts(porcelain: string): Checkout[] {
	return porcelain
		.trim()
		.split("\n\n")
		.map((block) => {
			const field = (key: string) => block.match(new RegExp(`^${key} (.*)$`, "m"))?.[1] ?? "";
			return { path: field("worktree"), head: field("HEAD"), branch: field("branch").replace(BRANCH_PREFIX, "") };
		});
}

function isInside(directory: string | undefined, root: string): boolean {
	if (!directory) return false;
	const relative = path.relative(root, directory);
	return !relative.startsWith("..") && !path.isAbsolute(relative);
}

async function workspaceFor(checkout: Checkout): Promise<Workspace | undefined> {
	return (await listWorkspaces()).find((workspace) => workspace.worktree?.checkout_path === checkout.path);
}

async function isAncestor(main: Checkout, checkout: Checkout): Promise<boolean> {
	return (await git(main.path, ["for-each-ref", "--contains", checkout.head, "--format=%(refname)", ...MAIN_REFS])).trim() !== "";
}

function remoteHost(url: string): string {
	const scp = url.match(SCP_REMOTE);
	if (scp) return scp[1].toLowerCase();
	try {
		return new URL(url).hostname.toLowerCase();
	} catch {
		return "";
	}
}

async function hasGitHubOrigin(main: Checkout): Promise<boolean> {
	try {
		return remoteHost((await git(main.path, ["remote", "get-url", "origin"])).trim()) === GITHUB_HOST;
	} catch {
		return false;
	}
}

async function hasMergedPullRequest(main: Checkout, branch: string): Promise<boolean> {
	if (!(await hasGitHubOrigin(main))) return false;
	try {
		const { stdout } = await execFileAsync("gh", ["pr", "list", "--state", "merged", "--head", branch, "--json", "number"], { cwd: main.path, timeout: HERDR_TIMEOUT_MS });
		return (JSON.parse(stdout) as unknown[]).length > 0;
	} catch {
		return false;
	}
}

async function gitKeepReason(main: Checkout, checkout: Checkout): Promise<string | undefined> {
	if (!checkout.branch) return "head is detached";
	if (MAIN_REFS.includes(`${BRANCH_PREFIX}${checkout.branch}`)) return "branch is main";
	if ((await git(checkout.path, ["status", "--porcelain"])).trim()) return "has uncommitted or untracked files";
	if ((await git(main.path, ["reflog", "show", "--format=%H", `${BRANCH_PREFIX}${checkout.branch}`])).trim().split("\n").length === 1) return NO_COMMITS_REASON;
	const merged = await isAncestor(main, checkout);
	const squashMerged = !merged && (await hasMergedPullRequest(main, checkout.branch));
	if (!merged && !squashMerged) return "branch is not merged into main";
	const tipSeconds = Number((await git(checkout.path, ["log", "-1", "--format=%ct", checkout.head])).trim());
	const changedMs = Math.max(tipSeconds * MS_PER_SECOND, fs.statSync(checkout.path).mtimeMs);
	if (Date.now() - changedMs < FRESH_HOURS * MS_PER_HOUR) return `changed in the last ${FRESH_HOURS} hours`;
	return undefined;
}

async function keepReasonUnlessCandidate(main: Checkout, checkout: Checkout): Promise<string | undefined> {
	const reason = await gitKeepReason(main, checkout);
	if (reason) return reason;
	const panes = await listPanes();
	const existing = await workspaceFor(checkout);
	if (panes.some((pane) => isInside(pane.cwd, checkout.path) || isInside(pane.foreground_cwd, checkout.path))) return "a pane is still inside it";
	if (existing && panes.some((pane) => pane.workspace_id === existing.workspace_id)) return "its Herdr workspace is still open";
	return undefined;
}

export async function sweepWorktrees(): Promise<WorktreeResult> {
	const result: WorktreeResult = { candidates: [], kept: [] };
	const [main, ...linked] = await git(".", ["worktree", "list", "--porcelain"]).then(parseCheckouts, () => []);
	for (const checkout of linked) {
		const entry = { path: checkout.path, branch: checkout.branch };
		try {
			const kept = await keepReasonUnlessCandidate(main, checkout);
			if (kept) result.kept.push({ ...entry, reason: kept });
			else result.candidates.push({ ...entry, reason: CANDIDATE_REASON });
		} catch (error) {
			result.kept.push({ ...entry, reason: `check failed: ${String(error).split("\n")[0]}` });
		}
	}
	return result;
}

export function isTopLevelLead(env: Record<string, string | undefined>): boolean {
	return env.HERDR_ENV === "1" && !env.PI_HERDSMAN_MAILBOX && !env.PI_SUBAGENT_CHILD;
}

export type Proc = { pid: number; uid: number; ppid: number; pgid: number; state: string; cpuPercent: number; cpuSeconds: number; started: string; command: string };
export type Marker = { agent: boolean; paneId?: string };
export type OrphanOptions = { selfPids: number[]; uid: number; workspaceId: string };
export type Orphan = { proc: Proc; reason: string; paneId?: string; sessionLeader: boolean };
export type OrphanDeps = {
	list: () => Promise<Proc[]>;
	recheck: (pid: number) => Promise<Proc | undefined>;
	kill: (pid: number) => void;
	marker: (pid: number) => Promise<Marker>;
	livePaneIds: () => Promise<string[]>;
};
export type OrphanResult = { killed: Orphan[]; wouldKill: Orphan[] };

const PROCESS_LINE = /^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+([\d.]+)\s+([\d:.]+)\s+(\w{3}\s+\w{3}\s+\d+\s+[\d:]+\s+\d{4})\s+(.*)$/;
const AGENT_VARIABLE = /(?:^| )PI_CODING_AGENT=(\S*)/g;
const PANE_VARIABLE = /(?:^| )HERDR_PANE_ID=(\S+)/g;
const AGENT_VALUE = "true";
const PANE_ID_SEPARATOR = ":";
const SESSION_LEADER_STATE = /s/;

export function parseProcessList(output: string): Proc[] {
	const procs: Proc[] = [];
	for (const line of output.split("\n")) {
		const match = line.match(PROCESS_LINE);
		if (!match) continue;
		const [, pid, uid, ppid, pgid, state, cpuPercent, time, started, command] = match;
		const cpuSeconds = time.split(":").reduce((total, part) => total * SECONDS_PER_MINUTE + Number(part), 0);
		procs.push({ pid: Number(pid), uid: Number(uid), ppid: Number(ppid), pgid: Number(pgid), state, cpuPercent: Number(cpuPercent), cpuSeconds, started, command });
	}
	return procs;
}

function lastMatch(text: string, pattern: RegExp): string | undefined {
	return [...text.matchAll(pattern)].at(-1)?.[1];
}

export function parseMarker(commandLine: string): Marker {
	return { agent: lastMatch(commandLine, AGENT_VARIABLE) === AGENT_VALUE, paneId: lastMatch(commandLine, PANE_VARIABLE) };
}

export function isOrphanCandidate(proc: Proc, options: OrphanOptions): boolean {
	return proc.ppid === INIT_PID && proc.uid === options.uid && !options.selfPids.includes(proc.pid);
}

function orphanReason(marker: Marker | undefined, livePanes: Set<string>, workspaceId: string): string | undefined {
	if (!marker?.agent || !marker.paneId?.startsWith(`${workspaceId}${PANE_ID_SEPARATOR}`)) return undefined;
	return livePanes.has(marker.paneId) ? undefined : `agent pane ${marker.paneId} is gone`;
}

export function selectOrphans(procs: Proc[], markers: Record<number, Marker>, livePaneIds: string[], options: OrphanOptions): Orphan[] {
	if (!livePaneIds.length) return [];
	const livePanes = new Set(livePaneIds);
	const selected: Orphan[] = [];
	for (const proc of procs) {
		if (!isOrphanCandidate(proc, options)) continue;
		const marker = markers[proc.pid];
		const reason = orphanReason(marker, livePanes, options.workspaceId);
		if (reason) selected.push({ proc, reason, paneId: marker?.paneId, sessionLeader: SESSION_LEADER_STATE.test(proc.state) });
	}
	return selected;
}

async function runPs(args: string[]): Promise<string> {
	return (await execFileAsync("ps", args, { timeout: PS_TIMEOUT_MS, env: { ...process.env, LC_ALL: "C" } })).stdout;
}

async function listProcesses(): Promise<Proc[]> {
	return parseProcessList(await runPs(["-axo", PS_FIELDS]));
}

async function recheckProcess(pid: number): Promise<Proc | undefined> {
	try {
		return parseProcessList(await runPs(["-o", PS_FIELDS, "-p", String(pid)]))[0];
	} catch {
		return undefined;
	}
}

async function readMarker(pid: number): Promise<Marker> {
	try {
		return parseMarker(await runPs(["eww", "-o", "command=", "-p", String(pid)]));
	} catch {
		return { agent: false };
	}
}

export async function livePaneIds(): Promise<string[]> {
	try {
		return (await listPanes()).map((pane) => pane.pane_id);
	} catch {
		return [];
	}
}

const realOrphanDeps: OrphanDeps = { list: listProcesses, recheck: recheckProcess, kill: (pid) => process.kill(pid, "SIGKILL"), marker: readMarker, livePaneIds };

export function orphanOptions(workspaceId: string): OrphanOptions {
	return { selfPids: [process.pid, process.ppid], uid: process.getuid?.() ?? -1, workspaceId };
}

export function isDryRun(env: Record<string, string | undefined>): boolean {
	return !!env[DRY_RUN_VARIABLE] && env[DRY_RUN_VARIABLE] !== "0";
}

export async function sweepOrphans(options: OrphanOptions, dryRun: boolean, deps: OrphanDeps = realOrphanDeps): Promise<OrphanResult> {
	const result: OrphanResult = { killed: [], wouldKill: [] };
	const paneIds = await deps.livePaneIds();
	if (!paneIds.length) return result;
	const procs = await deps.list();
	const markers: Record<number, Marker> = {};
	await Promise.all(procs.filter((proc) => isOrphanCandidate(proc, options)).map(async (proc) => (markers[proc.pid] = await deps.marker(proc.pid))));
	for (const orphan of selectOrphans(procs, markers, paneIds, options)) {
		if (dryRun) {
			result.wouldKill.push(orphan);
			continue;
		}
		const current = await deps.recheck(orphan.proc.pid);
		if (current?.started !== orphan.proc.started || current.command !== orphan.proc.command) continue;
		deps.kill(orphan.proc.pid);
		result.killed.push(orphan);
	}
	return result;
}

export type Config = { enabled: boolean; graceSeconds: number; intervalSeconds: number };

function readJson(file: string): Record<string, unknown> {
	try {
		return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
	} catch {
		return {};
	}
}

function numberOr(value: unknown, fallback: number): number {
	return typeof value === "number" ? value : fallback;
}

export function readConfig(file: string): Config {
	const config = readJson(file);
	return {
		enabled: config.enabled !== false,
		graceSeconds: Math.max(0, numberOr(config.graceSeconds, DEFAULT_GRACE_SECONDS)),
		intervalSeconds: Math.max(MIN_INTERVAL_SECONDS, numberOr(config.intervalSeconds, DEFAULT_INTERVAL_SECONDS)),
	};
}

export function writeEnabledSetting(file: string, enabled: boolean): void {
	fs.writeFileSync(file, `${JSON.stringify({ ...readJson(file), enabled }, null, 2)}\n`);
}

function describe(candidate: Candidate): string {
	return `${candidate.paneId} (${candidate.label}): ${candidate.reason}`;
}

function describeWorktree(worktree: Worktree): string {
	return `${worktree.path} (${worktree.branch}): ${worktree.reason}`;
}

function describeOrphan(orphan: Orphan): string {
	const leader = orphan.sessionLeader ? ", session leader" : "";
	return `PID ${orphan.proc.pid} (${orphan.reason}${leader}): ${orphan.proc.command.slice(0, COMMAND_PREVIEW_LENGTH)}`;
}

export default function (pi: ExtensionAPI) {
	const configPath = path.join(getAgentDir(), CONFIG_FILE);
	let timer: ReturnType<typeof setInterval> | undefined;
	const told = new Set<string>();
	let keptSignature = "";

	function optionsFor(config: Config, workspaceId: string): SweepOptions {
		return { now: Date.now(), graceSeconds: config.graceSeconds, selfSessionId: process.env.PI_SESSION_ID ?? "", workspaceId };
	}

	function tellOnce(ui: ExtensionContext["ui"], key: string, message: string, level: "info" | "warning"): void {
		if (told.has(key)) return;
		told.add(key);
		ui.notify(message, level);
	}

	function tellKept(ui: ExtensionContext["ui"], kept: Worktree[], listAll: boolean): void {
		const signature = kept.map(describeWorktree).sort().join("\n");
		if (!kept.length || (!listAll && signature === keptSignature)) {
			keptSignature = signature;
			return;
		}
		keptSignature = signature;
		const message = listAll ? `pane-reaper kept worktrees: ${kept.map(describeWorktree).join("; ")}` : `pane-reaper kept ${kept.length} ${kept.length === 1 ? "worktree" : "worktrees"} (see /pane-reaper)`;
		ui.notify(message, "info");
	}

	async function check(ui: ExtensionContext["ui"], config: Config, listAll = false): Promise<number> {
		const workspaceId = await currentWorkspaceId();
		if (!workspaceId) return 0;
		const result = await sweep(optionsFor(config, workspaceId));
		for (const candidate of result.closed) ui.notify(`pane-reaper closed ${describe(candidate)}`, "info");
		for (const candidate of result.asked) {
			const message = `pane-reaper: ${describe(candidate)}. Close it with /pane-reaper close ${candidate.paneId}`;
			tellOnce(ui, `${candidate.paneId}:${candidate.reason}`, message, "warning");
		}
		const orphans = await sweepOrphans(orphanOptions(workspaceId), isDryRun(process.env));
		for (const orphan of orphans.killed) ui.notify(`pane-reaper killed ${describeOrphan(orphan)}`, "warning");
		for (const orphan of orphans.wouldKill) tellOnce(ui, `orphan:${orphan.proc.pid}:${orphan.proc.started}`, `pane-reaper (dry run) would kill ${describeOrphan(orphan)}`, "warning");
		const { candidates, kept } = await sweepWorktrees();
		for (const worktree of candidates) tellOnce(ui, `worktree:${worktree.path}`, `pane-reaper: worktree ${describeWorktree(worktree)}. Safe to remove`, "info");
		tellKept(ui, kept, listAll);
		return result.closed.length + result.asked.length + orphans.killed.length + orphans.wouldKill.length + candidates.length + kept.length;
	}

	async function tick(ui: ExtensionContext["ui"]): Promise<void> {
		try {
			await check(ui, readConfig(configPath));
		} catch (error) {
			tellOnce(ui, `error:${String(error)}`, `pane-reaper check failed: ${String(error)}`, "warning");
		}
	}

	function stopTimer(): void {
		clearInterval(timer);
		timer = undefined;
	}

	function startTimer(ui: ExtensionContext["ui"]): void {
		stopTimer();
		timer = setInterval(() => void tick(ui), readConfig(configPath).intervalSeconds * MS_PER_SECOND);
		timer.unref();
		void tick(ui);
	}

	async function runCommand(args: string, ctx: ExtensionCommandContext): Promise<void> {
		if (ctx.mode !== "tui") return;
		const [word, paneId] = args.trim().split(/\s+/);
		if (word === "on" || word === "off") {
			writeEnabledSetting(configPath, word === "on");
			if (word === "on" && isTopLevelLead(process.env)) startTimer(ctx.ui);
			if (word === "off") stopTimer();
			ctx.ui.notify(`pane-reaper ${word}`, "info");
		} else if (word === "close" && paneId) {
			const workspaceId = await currentWorkspaceId();
			const closed = workspaceId && (await closeFlagged(optionsFor(readConfig(configPath), workspaceId), paneId));
			ctx.ui.notify(closed ? `pane-reaper closed ${describe(closed)}` : `pane-reaper: ${paneId} is not a flagged orphan`, closed ? "info" : "warning");
		} else if (word) {
			ctx.ui.notify(USAGE, "warning");
		} else {
			told.clear();
			if ((await check(ctx.ui, readConfig(configPath), true)) === 0) ctx.ui.notify("pane-reaper: no orphaned panes", "info");
		}
	}

	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		if (process.env.HERDR_ENV !== "1") tellOnce(ctx.ui, "no-herdr", NO_HERDR_WARNING, "warning");
		if (isTopLevelLead(process.env) && readConfig(configPath).enabled) startTimer(ctx.ui);
	});
	pi.on("session_shutdown", () => stopTimer());
	pi.registerCommand("pane-reaper", {
		description: "Close finished Herdr agent panes whose lead is gone, kill orphaned processes left behind by dead agent panes (set PANE_REAPER_DRY_RUN=1 to only report them), and report merged clean feature worktrees that are safe to remove. It never removes a worktree or branch. `on|off` toggles the periodic check, `close <pane-id>` closes a reported pane.",
		handler: runCommand,
	});
}
