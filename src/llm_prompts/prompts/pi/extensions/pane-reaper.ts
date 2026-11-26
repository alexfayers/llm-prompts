// Removes finished worktrees and kills orphaned processes left by dead agent panes in Herdr, all within the current workspace.
// Commands: /pane-reaper on|off
// Config: pane-reaper.json keys enabled, intervalSeconds
// Env: HERDR_ENV (1 when running inside Herdr)
// Env: PI_SUBAGENT_CHILD (set for subagents, which never run the periodic check)
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { forkRegistry } from "./pi-context/registry.ts";

const execFileAsync = promisify(execFile);
const CONFIG_FILE = "pane-reaper.json";
const USAGE = "Usage: /pane-reaper [on|off]";
const MS_PER_SECOND = 1000;
const MS_PER_HOUR = 60 * 60 * MS_PER_SECOND;
const FRESH_HOURS = 24;
const HERDR_TIMEOUT_MS = 5000;
const DEFAULT_INTERVAL_SECONDS = 60;
const MIN_INTERVAL_SECONDS = 10;
const PS_TIMEOUT_MS = 5000;
const LSOF_CWD_ARGS = ["-a", "-d", "cwd", "-Fn"];
const LSOF_NAME_PREFIX = "n";
const PS_FIELDS = "pid=,uid=,ppid=,pgid=,stat=,%cpu=,time=,lstart=,command=";
const INIT_PID = 1;
const COMMAND_PREVIEW_LENGTH = 80;
const SECONDS_PER_MINUTE = 60;

type Pane = {
	pane_id: string;
	workspace_id?: string;
	cwd?: string;
	foreground_cwd?: string;
};
export type Worktree = { path: string; branch: string; head: string; reason: string };
export type WorktreeResult = { candidates: Worktree[]; kept: Worktree[] };
type MergedHead = { headRefName: string; headRefOid: string };
type Checkout = { path: string; head: string; branch: string };
type Workspace = { workspace_id: string; worktree?: { checkout_path?: string } };

const CANDIDATE_REASON = "merged into main and clean";
const BRANCH_PREFIX = "refs/heads/";
const MAIN_REFS = ["main", "master"].flatMap((name) => [`${BRANCH_PREFIX}${name}`, `refs/remotes/origin/${name}`]);
const GITHUB_HOST = "github.com";
const SCP_REMOTE = /^(?:[^@/:]+@)?([^:/]+):(?!\/\/)/;
const MERGED_PR_LIMIT = 200;
const CONTRIBUTE_HEAD = /^[^/]+\/contribute\//;
const mergedBranches = new Set<string>();
const notMergedCheckedAt = new Map<string, number>();
let mergedListing: Promise<MergedHead[] | undefined> | undefined;

function describeWorktree(worktree: Worktree): string {
	return `${worktree.path} (${worktree.branch}): ${worktree.reason}`;
}

const firstLine = (error: unknown): string => String(error).split("\n")[0];

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
	if ((await git(main.path, ["for-each-ref", "--contains", checkout.head, "--format=%(refname)", ...MAIN_REFS])).trim() === "") return false;
	mergedBranches.add(mergedKey(checkout));
	return true;
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

async function listMergedHeads(main: Checkout): Promise<MergedHead[] | undefined> {
	try {
		const { stdout } = await execFileAsync("gh", ["pr", "list", "--state", "merged", "--author", "@me", "--limit", String(MERGED_PR_LIMIT), "--json", "headRefName,headRefOid"], { cwd: main.path, timeout: HERDR_TIMEOUT_MS });
		return JSON.parse(stdout) as MergedHead[];
	} catch {
		return undefined;
	}
}

const mergedKey = (checkout: { branch: string; head: string }) => `${checkout.branch}@${checkout.head}`;

async function hasMergedPullRequest(main: Checkout, checkout: Checkout): Promise<boolean> {
	const key = mergedKey(checkout);
	if (mergedBranches.has(key)) return true;
	const checkedAt = notMergedCheckedAt.get(key);
	if (checkedAt !== undefined && Date.now() - checkedAt < MS_PER_HOUR) return false;
	if (!(await hasGitHubOrigin(main))) return false;
	mergedListing ??= listMergedHeads(main);
	const merged = await mergedListing;
	if (!merged) return false;
	if (!merged.some((pullRequest) => pullRequest.headRefOid === checkout.head && pullRequest.headRefName.replace(CONTRIBUTE_HEAD, "") === checkout.branch)) {
		notMergedCheckedAt.set(key, Date.now());
		return false;
	}
	mergedBranches.add(key);
	return true;
}

async function gitKeepReason(main: Checkout, checkout: Checkout): Promise<string | undefined> {
	if (!checkout.branch) return "head is detached";
	if (MAIN_REFS.includes(`${BRANCH_PREFIX}${checkout.branch}`)) return "branch is main";
	if ((await git(checkout.path, ["status", "--porcelain"])).trim()) return "has uncommitted or untracked files";
	const hasOwnCommits = (await git(main.path, ["reflog", "show", "--format=%H", `${BRANCH_PREFIX}${checkout.branch}`])).trim().split("\n").length > 1;
	if (!(await isAncestor(main, checkout)) && hasOwnCommits && !(await hasMergedPullRequest(main, checkout))) return "branch is not merged into main";
	const tipSeconds = Number((await git(checkout.path, ["log", "-1", "--format=%ct", checkout.head])).trim());
	const changedMs = Math.max(tipSeconds * MS_PER_SECOND, fs.statSync(checkout.path).mtimeMs);
	if (Date.now() - changedMs < FRESH_HOURS * MS_PER_HOUR) return `changed in the last ${FRESH_HOURS} hours`;
	return undefined;
}

// shortcut: sees only forks of this pi process, so another session's fork working from the primary checkout is missed. Upgrade if such a fork loses a worktree.
function isUsedByLiveFork(checkout: Checkout): boolean {
	return (forkRegistry()?.live() ?? []).some((run) => [run.tree?.path, run.worktree, run.target, run.cwd].some((directory) => isInside(directory, checkout.path)));
}

async function isProcessInside(checkout: Checkout): Promise<boolean> {
	const { stdout } = await execFileAsync("lsof", LSOF_CWD_ARGS, { timeout: PS_TIMEOUT_MS });
	return stdout.split("\n").some((line) => line.startsWith(LSOF_NAME_PREFIX) && isInside(line.slice(LSOF_NAME_PREFIX.length), checkout.path));
}

async function keepReasonUnlessCandidate(main: Checkout, checkout: Checkout): Promise<string | undefined> {
	const reason = await gitKeepReason(main, checkout);
	if (reason) return reason;
	const panes = await listPanes();
	const existing = await workspaceFor(checkout);
	if (panes.some((pane) => isInside(pane.cwd, checkout.path) || isInside(pane.foreground_cwd, checkout.path))) return "a pane is still inside it";
	if (existing && panes.some((pane) => pane.workspace_id === existing.workspace_id)) return "its Herdr workspace is still open";
	if (isUsedByLiveFork(checkout)) return "a live fork uses it";
	if (await isProcessInside(checkout)) return "a process is still inside it";
	return undefined;
}

export async function sweepWorktrees(): Promise<WorktreeResult> {
	const result: WorktreeResult = { candidates: [], kept: [] };
	mergedListing = undefined;
	const [main, ...linked] = await git(".", ["worktree", "list", "--porcelain"]).then(parseCheckouts, () => []);
	for (const checkout of linked) {
		const entry = { path: checkout.path, branch: checkout.branch, head: checkout.head };
		try {
			const kept = await keepReasonUnlessCandidate(main, checkout);
			if (kept) result.kept.push({ ...entry, reason: kept });
			else result.candidates.push({ ...entry, reason: CANDIDATE_REASON });
		} catch (error) {
			result.kept.push({ ...entry, reason: `check failed: ${firstLine(error)}` });
		}
	}
	return result;
}

async function removeWorktree(worktree: Worktree): Promise<{ message: string; level: "info" | "warning" }> {
	try {
		// shortcut: without --force git still deletes ignored files such as overlay.json. Upgrade if one holds work worth keeping.
		await git(".", ["worktree", "remove", worktree.path]);
	} catch (error) {
		return { message: `pane-reaper could not remove worktree ${worktree.path} (${worktree.branch}): ${firstLine(error)}`, level: "warning" };
	}
	const removed = `pane-reaper removed worktree ${describeWorktree(worktree)}`;
	try {
		// git branch -d refuses a branch merged into main but not into the checkout's branch or upstream, so delete a proven-merged branch only while it still points at the merged head.
		if (mergedBranches.has(mergedKey(worktree))) await git(".", ["update-ref", "-d", `${BRANCH_PREFIX}${worktree.branch}`, worktree.head]);
		else await git(".", ["branch", "-d", worktree.branch]);
		return { message: removed, level: "info" };
	} catch (error) {
		return { message: `${removed}. Kept the branch: ${firstLine(error)}`, level: "warning" };
	}
}

export function isTopLevelLead(env: Record<string, string | undefined>): boolean {
	return env.HERDR_ENV === "1" && !env.PI_SUBAGENT_CHILD;
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
export type OrphanResult = { killed: Orphan[] };

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

export async function sweepOrphans(options: OrphanOptions, deps: OrphanDeps = realOrphanDeps): Promise<OrphanResult> {
	const result: OrphanResult = { killed: [] };
	const paneIds = await deps.livePaneIds();
	if (!paneIds.length) return result;
	const procs = await deps.list();
	const markers: Record<number, Marker> = {};
	await Promise.all(procs.filter((proc) => isOrphanCandidate(proc, options)).map(async (proc) => (markers[proc.pid] = await deps.marker(proc.pid))));
	for (const orphan of selectOrphans(procs, markers, paneIds, options)) {
		const current = await deps.recheck(orphan.proc.pid);
		if (current?.started !== orphan.proc.started || current.command !== orphan.proc.command) continue;
		deps.kill(orphan.proc.pid);
		result.killed.push(orphan);
	}
	return result;
}

export type Config = { enabled: boolean; intervalSeconds: number };

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
		intervalSeconds: Math.max(MIN_INTERVAL_SECONDS, numberOr(config.intervalSeconds, DEFAULT_INTERVAL_SECONDS)),
	};
}

export function writeEnabledSetting(file: string, enabled: boolean): void {
	fs.writeFileSync(file, `${JSON.stringify({ ...readJson(file), enabled }, null, 2)}\n`);
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
	let unreported: { message: string; level: "info" | "warning" }[] = [];

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

	async function check(ui: ExtensionContext["ui"], listAll = false): Promise<number> {
		const workspaceId = await currentWorkspaceId();
		if (!workspaceId) return 0;
		const orphans = await sweepOrphans(orphanOptions(workspaceId));
		for (const orphan of orphans.killed) ui.notify(`pane-reaper killed ${describeOrphan(orphan)}`, "warning");
		const { candidates, kept } = await sweepWorktrees();
		const removals = [];
		for (const worktree of candidates) removals.push(await removeWorktree(worktree));
		if (listAll) {
			const reports = [...unreported, ...removals];
			for (const { message, level } of reports) ui.notify(message, level);
			unreported = [];
			tellKept(ui, kept, listAll);
			return orphans.killed.length + reports.length + kept.length;
		}
		unreported.push(...removals);
		if (removals.length) {
			keptSignature = kept.map(describeWorktree).sort().join("\n");
			ui.notify(`pane-reaper removed ${removals.length} ${removals.length === 1 ? "worktree" : "worktrees"}, kept ${kept.length} (see /pane-reaper)`, removals.some(({ level }) => level === "warning") ? "warning" : "info");
		} else tellKept(ui, kept, listAll);
		return orphans.killed.length + candidates.length + kept.length;
	}

	async function tick(ui: ExtensionContext["ui"]): Promise<void> {
		try {
			await check(ui);
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
		const word = args.trim();
		if (word === "on" || word === "off") {
			writeEnabledSetting(configPath, word === "on");
			if (word === "on" && isTopLevelLead(process.env)) startTimer(ctx.ui);
			if (word === "off") stopTimer();
			ctx.ui.notify(`pane-reaper ${word}`, "info");
		} else if (word) {
			ctx.ui.notify(USAGE, "warning");
		} else {
			told.clear();
			if ((await check(ctx.ui, true)) === 0) ctx.ui.notify("pane-reaper: nothing to report", "info");
		}
	}

	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		if (isTopLevelLead(process.env) && readConfig(configPath).enabled) startTimer(ctx.ui);
	});
	pi.on("session_shutdown", () => stopTimer());
	pi.registerCommand("pane-reaper", {
		description: "Kill orphaned processes left behind by dead Herdr agent panes, and remove merged clean feature worktrees and their branches that nothing uses, with `git worktree remove` and `git branch -d`, deleting a branch proven merged into main only while it is at the merged head, and never `--force` or `-D`. `on|off` toggles the periodic check.",
		handler: runCommand,
	});
}
