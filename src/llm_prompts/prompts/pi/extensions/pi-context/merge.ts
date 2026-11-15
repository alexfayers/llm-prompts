// Creates a git worktree for a writer delegate and lands its commits on the main checkout through a one-at-a-time queue: rebase, fold fixups, test, fast-forward.
// Env: PI_CONTEXT_TEST_CMD (test command run in the worktree before landing; default detected from the repository's files by test-gates.json), PI_CONTEXT_LAND_FOLD=off (land `fixup!`, `squash!` and `amend!` commits as they are, instead of folding them into their target in the fork's range or in main's unpushed range)
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const MAX_RETURNS = 2;
export const MAX_MAIN_MOVED = 3;
const OUTPUT_TAIL = 4000;

export type Event =
	| { type: "fork-done" }
	| { type: "fork-failed"; reason: string }
	| { type: "fork-blocked"; reason: string }
	| { type: "dirty" }
	| { type: "wrong-branch"; branch: string; head: string }
	| { type: "no-commits" }
	| { type: "rebased" }
	| { type: "conflict"; base: string; files: string[] }
	| { type: "no-tests" }
	| { type: "tests-green" }
	| { type: "tests-red"; output: string }
	| { type: "tree-changed-by-tests" }
	| { type: "ff-ok"; sha: string }
	| { type: "main-moved" }
	| { type: "main-dirty" };

export type Action =
	| { type: "rebase" }
	| { type: "test" }
	| { type: "ff" }
	| { type: "return-to-fork"; message: string }
	| { type: "cleanup"; sha?: string }
	| { type: "escalate"; reason: string };

export interface Entry {
	state: "queued" | "rebasing" | "testing" | "landing" | "landed" | "returned" | "escalated";
	/** Times the fork was sent back to fix a problem. */
	returns: number;
	/** Times main moved while the fork was landing. */
	moved: number;
	/** The repository has no test command, so the work lands untested. */
	untested?: boolean;
}

type Step = { entry: Entry; action: Action };

const escalate = (entry: Entry, reason: string): Step => ({ entry: { ...entry, state: "escalated" }, action: { type: "escalate", reason } });

function returnToFork(entry: Entry, message: string, reason: string): Step {
	if (entry.returns >= MAX_RETURNS) return escalate(entry, reason);
	return { entry: { ...entry, state: "returned", returns: entry.returns + 1 }, action: { type: "return-to-fork", message } };
}

/** Moves a landing one step: the next state and the action to run. Pure. */
export function step(entry: Entry, event: Event): Step {
	switch (event.type) {
		case "fork-failed":
			return escalate(entry, `fork failed: ${event.reason}`);
		case "fork-blocked":
			return escalate(entry, `fork is blocked: ${event.reason}`);
		case "fork-done":
			if (entry.state === "queued" || entry.state === "returned") return { entry: { ...entry, state: "rebasing" }, action: { type: "rebase" } };
			break;
		case "wrong-branch":
			if (entry.state === "rebasing") return returnToFork(entry, `The worktree is on ${event.head}, not ${event.branch}. Put your commits on ${event.branch} and switch back to it.`, `the worktree left ${event.branch} for ${event.head}`);
			return escalate(entry, `the worktree left ${event.branch} for ${event.head}`);
		case "dirty":
			if (entry.state === "rebasing") return returnToFork(entry, "The worktree has uncommitted changes. Commit them, or discard what should not land.", "the worktree keeps uncommitted changes");
			break;
		case "no-commits":
			if (entry.state === "rebasing") return { entry: { ...entry, state: "landed" }, action: { type: "cleanup" } };
			break;
		case "rebased":
			if (entry.state === "rebasing") return { entry: { ...entry, state: "testing" }, action: { type: "test" } };
			break;
		case "conflict":
			if (entry.state === "rebasing") {
				const files = event.files.join(", ");
				return returnToFork(entry, `Rebasing onto ${event.base} conflicts in: ${files}. Run \`git rebase --fork-point ${event.base}\`, resolve the conflicts, finish the rebase and commit.`, `rebase conflicts in ${files}`);
			}
			break;
		case "no-tests":
			if (entry.state === "testing") return { entry: { ...entry, state: "landing", untested: true }, action: { type: "ff" } };
			break;
		case "tests-green":
			if (entry.state === "testing") return { entry: { ...entry, state: "landing" }, action: { type: "ff" } };
			break;
		case "tests-red":
			if (entry.state === "testing") return returnToFork(entry, `The tests fail. Fix them and commit. Output:\n${event.output}`, `tests fail:\n${event.output}`);
			break;
		case "tree-changed-by-tests":
			if (entry.state === "testing") return returnToFork(entry, "Running the tests changed tracked or untracked files in the worktree. Commit or remove them.", "running the tests changes files in the worktree");
			break;
		case "ff-ok":
			if (entry.state === "landing") return { entry: { ...entry, state: "landed" }, action: { type: "cleanup", sha: event.sha } };
			break;
		case "main-moved":
			if (entry.state !== "landing") break;
			if (entry.moved >= MAX_MAIN_MOVED) return escalate(entry, "the main branch kept moving");
			return { entry: { ...entry, state: "rebasing", moved: entry.moved + 1 }, action: { type: "rebase" } };
		case "main-dirty":
			if (entry.state === "landing") return escalate(entry, "the main checkout changed during the fork");
			break;
	}
	return escalate(entry, `unexpected ${event.type} while ${entry.state}`);
}

interface Ran {
	code: number;
	out: string;
}

const run = (command: string, args: string[], cwd: string, signal?: AbortSignal, env?: NodeJS.ProcessEnv) =>
	new Promise<Ran>((resolve) => {
		execFile(command, args, { cwd, signal, env, maxBuffer: 64 * 1024 * 1024 }, (error, stdout, stderr) => {
			const code = error ? (typeof error.code === "number" ? error.code : 1) : 0;
			resolve({ code, out: stdout + stderr + (error && typeof error.code !== "number" ? error.message : "") });
		});
	});

const git = (cwd: string, ...args: string[]) => run("git", args, cwd);

async function gitOut(cwd: string, ...args: string[]): Promise<string> {
	const { code, out } = await git(cwd, ...args);
	if (code) throw new Error(`git ${args.join(" ")} failed: ${out.trim()}`);
	return out.trim();
}

export interface Worktree {
	repo: string;
	path: string;
	branch: string;
	/** The branch the main checkout had when the worktree was made, and where the work lands. */
	base: string;
	/** The main checkout's state when the worktree was made. */
	snapshot: string;
}

const mainSnapshot = async (repo: string) => `${await gitOut(repo, "symbolic-ref", "--short", "HEAD")}\n${await gitOut(repo, "status", "--porcelain")}`;

type Gate = { all?: string[]; any?: string[]; match?: { file?: string; pattern: string }; command: string };
type Dependency = { lock: string; installed: string; command: string[] };
const GATES: { gates: Gate[]; dependencies: Dependency[] } = JSON.parse(fs.readFileSync(fileURLToPath(new URL("./test-gates.json", import.meta.url)), "utf8"));

/** Returns the test command test-gates.json detects from the repository's files, or undefined. */
export function detectGate(dir: string): string | undefined {
	const has = (file: string) => fs.existsSync(path.join(dir, file));
	return GATES.gates.find(({ all = [], any, match }) => {
		if (!all.every(has) || (any && !any.some(has))) return false;
		const file = match && (match.file ?? [...all, ...(any ?? [])].find(has));
		return !match || (file !== undefined && new RegExp(match.pattern, "m").test(fs.readFileSync(path.join(dir, file), "utf8")));
	})?.command;
}

/** Installs, offline, the dependencies of each lockfile whose packages the main checkout has installed, once per install directory. */
async function installDependencies(repo: string, dir: string): Promise<void> {
	const has = (file: string) => fs.existsSync(path.join(repo, file));
	const done = new Set<string>();
	for (const { lock, installed, command: [command, ...args] } of GATES.dependencies) {
		if (done.has(installed) || !has(lock) || !has(installed)) continue;
		done.add(installed);
		await run(command, args, dir);
	}
}

/** Makes a worktree on `fork/<name>` under `root` from the branch of the repository at `cwd`. */
export async function createWorktree(cwd: string, root: string, name: string): Promise<Worktree> {
	const repo = await gitOut(cwd, "rev-parse", "--show-toplevel");
	if (fs.realpathSync(repo) !== fs.realpathSync(cwd)) throw new Error(`Writers need the repository root as the directory, not ${cwd}.`);
	const base = await gitOut(repo, "symbolic-ref", "--short", "HEAD");
	const dir = path.join(root, `${path.basename(repo)}-${createHash("sha1").update(repo).digest("hex").slice(0, 8)}`, name);
	const branch = `fork/${name}`;
	const snapshot = await mainSnapshot(repo);
	await gitOut(repo, "worktree", "add", "-b", branch, dir, base);
	await installDependencies(repo, dir);
	return { repo, path: dir, branch, base, snapshot };
}

/** Reports the worktree's HEAD when it is not the fork's branch. */
async function offBranch(tree: Worktree): Promise<Event | undefined> {
	const head = (await git(tree.path, "symbolic-ref", "-q", "HEAD")).out.trim();
	return head === `refs/heads/${tree.branch}` ? undefined : { type: "wrong-branch", branch: tree.branch, head: head || "a detached HEAD" };
}

async function rebase(tree: Worktree): Promise<Event> {
	const off = await offBranch(tree);
	if (off) return off;
	if ((await gitOut(tree.path, "status", "--porcelain")) !== "") return { type: "dirty" };
	if ((await gitOut(tree.path, "rev-list", "--count", `${tree.base}..HEAD`)) === "0") return { type: "no-commits" };
	if ((await git(tree.path, "rebase", "--fork-point", tree.base)).code === 0) {
		if (foldOn()) await autosquash(tree.path, tree.base);
		return { type: "rebased" };
	}
	const files = (await gitOut(tree.path, "diff", "--name-only", "--diff-filter=U")).split("\n").filter(Boolean);
	await gitOut(tree.path, "rebase", "--abort");
	return { type: "conflict", base: tree.base, files };
}

async function test(tree: Worktree, signal?: AbortSignal): Promise<Event> {
	const command = process.env.PI_CONTEXT_TEST_CMD ?? detectGate(tree.path);
	if (command === undefined) return { type: "no-tests" };
	const { code, out } = await run("sh", ["-c", command], tree.path, signal);
	if (code) return { type: "tests-red", output: out.slice(-OUTPUT_TAIL) };
	return (await gitOut(tree.path, "status", "--porcelain")) === "" ? { type: "tests-green" } : { type: "tree-changed-by-tests" };
}

const foldOn = () => process.env.PI_CONTEXT_LAND_FOLD !== "off";
const FOLD_PREFIX = /^(?:(?:fixup|squash|amend)! )+/;

/** Folds `fixup!`, `squash!` and `amend!` commits after `onto` into their targets, or leaves the branch as it was on a conflict. */
async function autosquash(cwd: string, onto: string): Promise<boolean> {
	const env = { ...process.env, GIT_SEQUENCE_EDITOR: ":", GIT_EDITOR: ":" };
	if ((await run("git", ["rebase", "-i", "--autosquash", onto], cwd, undefined, env)).code === 0) return true;
	await git(cwd, "rebase", "--abort");
	return false;
}

/** Returns where main's unpushed commits start: its upstream, else its merge-base with the remote's default branch. */
async function pushedBase(repo: string): Promise<string | undefined> {
	const upstream = await git(repo, "rev-parse", "--verify", "-q", "@{upstream}");
	if (upstream.code === 0) return upstream.out.trim();
	const remotes = (await git(repo, "remote")).out.split("\n").filter(Boolean);
	const remote = remotes.includes("origin") ? "origin" : remotes[0];
	if (!remote || (await git(repo, "rev-parse", "--verify", "-q", `refs/remotes/${remote}/HEAD`)).code) return undefined;
	const base = await git(repo, "merge-base", "HEAD", `refs/remotes/${remote}/HEAD`);
	return base.code ? undefined : base.out.trim();
}

const inProgress = async (repo: string) => {
	const states = ["rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"];
	const found = await Promise.all(states.map(async (name) => fs.existsSync(path.resolve(repo, await gitOut(repo, "rev-parse", "--git-path", name)))));
	return found.includes(true);
};

/** Folds the landed fixups whose target is an earlier unpushed commit of main into it. Never rewrites a pushed commit. */
async function foldIntoMain(repo: string, landedFrom: string): Promise<boolean> {
	const base = await pushedBase(repo);
	if (!base || (await gitOut(repo, "status", "--porcelain")) !== "" || (await inProgress(repo))) return false;
	const range = ["HEAD", "--not", base, "--remotes"];
	if ((await gitOut(repo, "rev-list", "--merges", "--count", ...range)) !== "0") return false;
	const landed = new Set((await gitOut(repo, "rev-list", `${landedFrom}..HEAD`)).split("\n"));
	const unpushed = (await gitOut(repo, "log", "--reverse", "--format=%H %P%x09%s", ...range)).split("\n").filter(Boolean).map((line) => {
		const [ids, subject] = line.split("\t");
		const [sha, parent] = ids.split(" ");
		return { sha, parent, subject };
	});
	const targets = unpushed.filter(({ sha }) => !landed.has(sha));
	const wanted = unpushed
		.filter(({ sha, subject }) => landed.has(sha) && FOLD_PREFIX.test(subject))
		.map(({ subject }) => subject.replace(FOLD_PREFIX, ""))
		.map((target) => (target ? targets.findIndex(({ sha, subject }) => !FOLD_PREFIX.test(subject) && (subject.startsWith(target) || sha.startsWith(target))) : -1))
		.filter((index) => index >= 0);
	const first = targets[Math.min(...wanted)];
	return first?.parent !== undefined && (await autosquash(repo, first.parent));
}

async function fastForward(tree: Worktree): Promise<Event> {
	const off = await offBranch(tree);
	if (off) return off;
	if ((await mainSnapshot(tree.repo)) !== tree.snapshot) return { type: "main-dirty" };
	const before = await gitOut(tree.repo, "rev-parse", "HEAD");
	if ((await git(tree.repo, "merge", "--ff-only", tree.branch)).code === 0) {
		if (foldOn() && (await foldIntoMain(tree.repo, before))) await git(tree.path, "reset", "-q", "--keep", tree.base);
		return { type: "ff-ok", sha: await gitOut(tree.repo, "rev-parse", "HEAD") };
	}
	const baseIsBehind = (await git(tree.repo, "merge-base", "--is-ancestor", tree.base, tree.branch)).code === 0;
	return { type: baseIsBehind ? "main-dirty" : "main-moved" };
}

/** Removes the landed worktree and branch without force, and says what stayed. */
async function cleanup(tree: Worktree): Promise<string | undefined> {
	const removed = await git(tree.repo, "worktree", "remove", tree.path);
	const deleted = await git(tree.repo, "branch", "-d", tree.branch);
	const failed = [removed, deleted].filter(({ code }) => code).map(({ out }) => out.trim());
	return failed.length ? `cleanup left files: ${failed.join("; ")}` : undefined;
}

/** Removes the worktree and its branch when the fork left no changes and no commits in it. */
export async function dropIfClean(tree: Worktree): Promise<boolean> {
	if (!fs.existsSync(tree.path)) return false;
	const status = await git(tree.path, "status", "--porcelain");
	const ahead = await git(tree.path, "rev-list", "--count", `${tree.base}..HEAD`);
	if (status.code || status.out.trim() || ahead.code || ahead.out.trim() !== "0") return false;
	return (await cleanup(tree)) === undefined;
}

/** Makes the worktree again on its branch, or on a new branch from its base, when it is gone. */
export async function restoreWorktree(tree: Worktree): Promise<void> {
	if (fs.existsSync(tree.path)) return;
	await git(tree.repo, "worktree", "prune");
	const hasBranch = (await git(tree.repo, "rev-parse", "--verify", "--quiet", `refs/heads/${tree.branch}`)).code === 0;
	await gitOut(tree.repo, "worktree", "add", ...(hasBranch ? [tree.path, tree.branch] : ["-b", tree.branch, tree.path, tree.base]));
	await installDependencies(tree.repo, tree.path);
}

export interface Landing {
	state: "landed" | "escalated";
	sha?: string;
	reason?: string;
	note?: string;
	/** The fork left the worktree clean, so it and its branch were removed. */
	removed?: boolean;
}

export interface LandOptions {
	tree: Worktree;
	/** What the fork's first reply amounts to. */
	first: Event;
	/** Sends a problem to the fork that wrote the work and waits for its next reply. */
	resume: (message: string) => Promise<Extract<Event, { type: "fork-done" | "fork-failed" | "fork-blocked" }>>;
	signal?: AbortSignal;
}

async function landNow({ tree, first, resume, signal }: LandOptions): Promise<Landing> {
	let entry: Entry = { state: "queued", returns: 0, moved: 0 };
	let event = first;
	for (;;) {
		const next = step(entry, event);
		entry = next.entry;
		const action = next.action;
		if (action.type === "cleanup") {
			const notes = [entry.untested && "untested: no test command found", await cleanup(tree)].filter(Boolean);
			return { state: "landed", sha: action.sha, note: notes.length ? notes.join("; ") : undefined };
		}
		if (action.type === "escalate") return { state: "escalated", reason: action.reason, removed: await dropIfClean(tree) };
		if (action.type === "rebase") event = await rebase(tree);
		else if (action.type === "test") event = await test(tree, signal);
		else if (action.type === "ff") event = await fastForward(tree);
		else event = await resume(action.message);
	}
}

let queue: Promise<unknown> = Promise.resolve();

/** Lands the worktree's commits on the main checkout, one landing at a time. Never pushes. */
export function land(options: LandOptions): Promise<Landing> {
	const landing = queue.then(() => landNow(options));
	queue = landing.then(undefined, () => undefined);
	return landing;
}
