// Creates a git worktree for a writer delegate, or takes one from a worktree provider another extension registers, and lands its commits on the main checkout, one landing at a time: check the commits, then fast-forward.
// Config: llmPrompts.forks.privateNames in pi settings (regex of private names that must not land, besides the home directory path)
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/** What the fork's reply amounts to. */
export type Event = { type: "fork-done" } | { type: "fork-failed"; reason: string } | { type: "fork-blocked"; reason: string };

/** Output ceiling for child processes whose output can exceed the 1 MiB Node default. */
export const EXEC_MAX_BUFFER_BYTES = 64 * 1024 * 1024;

interface Ran {
	code: number;
	out: string;
}

const run = (command: string, args: string[], cwd: string, signal?: AbortSignal, env?: NodeJS.ProcessEnv) =>
	new Promise<Ran>((resolve) => {
		execFile(command, args, { cwd, signal, env, maxBuffer: EXEC_MAX_BUFFER_BYTES }, (error, stdout, stderr) => {
			const code = error ? (typeof error.code === "number" ? error.code : 1) : 0;
			resolve({ code, out: stdout + stderr + (error && typeof error.code !== "number" ? error.message : "") });
		});
	});

const git = (cwd: string, ...args: string[]) => run("git", args, cwd);

export async function gitOut(cwd: string, ...args: string[]): Promise<string> {
	const { code, out } = await git(cwd, ...args);
	if (code) throw new Error(`git ${args.join(" ")} failed: ${out.trim()}`);
	return out.trim();
}

export interface Worktree {
	repo: string;
	path: string;
	/** The git checkout the fork commits in, when it is a directory inside `path`. */
	checkout?: string;
	/** A worktree provider made the worktree, and removes it. */
	provided?: boolean;
	branch: string;
	/** The branch the main checkout had when the worktree was made, and where the work lands. */
	base: string;
	/** The main checkout's state when the worktree was made. */
	snapshot: string;
	/** The writer's own branch, started from a base ref the caller named: its work lands only by being pushed. */
	own?: boolean;
	/** The commit the base branch was at when the worktree was made. */
	start?: string;
}

/** The main checkout's branch and uncommitted changes. */
export const mainSnapshot = async (repo: string) => `${await gitOut(repo, "symbolic-ref", "--short", "HEAD")}\n${await gitOut(repo, "status", "--porcelain")}`;

/** A short key naming a repository by its directory name and path. */
export const repoKey = (repo: string) => `${path.basename(repo)}-${createHash("sha1").update(repo).digest("hex").slice(0, 8)}`;

/** Makes a writer's worktree in place of a git worktree, registered on `globalThis[WORKTREE_PROVIDER]`. */
export interface WorktreeProvider {
	/** Makes a git checkout of `target` on a new branch `branch` from `base`, or returns undefined to leave it to a git worktree. `gitDir` names the checkout when it is a directory inside `path`. */
	create(target: string, branch: string, base: string): Promise<{ path: string; gitDir?: string } | undefined>;
	remove(path: string): Promise<void>;
}

export const WORKTREE_PROVIDER = Symbol.for("pi-context.worktree-provider");

const provider = () => (globalThis as { [WORKTREE_PROVIDER]?: WorktreeProvider })[WORKTREE_PROVIDER];

const PUSH_REMOTE = "origin";

/** The git checkout the fork commits in. */
const checkoutOf = (tree: Worktree) => tree.checkout ?? tree.path;

/** Adds a worktree on the new branch `branch` from `from`. An own branch gets the push remote branch of the same name as its upstream, so a plain `git push` works. */
async function addBranchWorktree(repo: string, dir: string, branch: string, from: string, own: boolean): Promise<void> {
	await gitOut(repo, "worktree", "add", "--no-track", "-b", branch, dir, from);
	if (!own) return;
	await gitOut(repo, "config", `branch.${branch}.remote`, PUSH_REMOTE);
	await gitOut(repo, "config", `branch.${branch}.merge`, `refs/heads/${branch}`);
}

/** Makes a worktree on `fork/<name>` from the branch of the repository at `cwd`: the worktree provider's, or else a git worktree under `root`. With `own`, the worktree is on the new branch `own.branch` from the ref `own.base`, and lands only by a push of that branch. */
export async function createWorktree(cwd: string, root: string, name: string, own?: { base?: string; branch?: string }): Promise<Worktree> {
	if (own?.base && !own.branch) throw new Error("base needs a branch name for the new branch");
	const repo = await gitOut(cwd, "rev-parse", "--show-toplevel");
	if (fs.realpathSync(repo) !== fs.realpathSync(cwd)) throw new Error(`Writers need the repository root as the directory, not ${cwd}.`);
	const base = own?.base ?? (await gitOut(repo, "symbolic-ref", "--short", "HEAD"));
	const branch = own?.branch ?? `fork/${name}`;
	if (own?.branch) await gitOut(repo, "check-ref-format", "--branch", branch);
	if (own?.branch) {
		await git(repo, "fetch", "-q", PUSH_REMOTE);
		if ((await git(repo, "rev-parse", "--verify", "--quiet", `refs/remotes/${PUSH_REMOTE}/${branch}`)).code === 0) throw new Error(`${branch} already exists on ${PUSH_REMOTE}`);
	}
	const snapshot = await mainSnapshot(repo);
	const start = await gitOut(repo, "rev-parse", base);
	const provided = await provider()?.create(repo, branch, base);
	if (provided) return { repo, path: provided.path, checkout: await gitOut(provided.gitDir ?? provided.path, "rev-parse", "--show-toplevel"), provided: true, branch, base, snapshot, ...(own?.branch && { own: true }), start };
	const dir = path.join(root, repoKey(repo), name);
	await addBranchWorktree(repo, dir, branch, base, Boolean(own?.branch));
	return { repo, path: dir, branch, base, snapshot, ...(own?.branch && { own: true }), start };
}

/** Reports the worktree's HEAD when it is not the fork's branch. */
async function offBranch(tree: Worktree): Promise<string | undefined> {
	const head = (await git(checkoutOf(tree), "symbolic-ref", "-q", "HEAD")).out.trim();
	return head === `refs/heads/${tree.branch}` ? undefined : `the worktree left ${tree.branch} for ${head || "a detached HEAD"}`;
}

const FOLD_PREFIX = /^(?:fixup|squash|amend)! /m;
const escapeRegExp = (text: string) => text.replace(/[.+?^${}()|[\]\\]/g, "\\$&");
const privateNames = (extra?: string) => new RegExp([escapeRegExp(os.homedir()), extra].filter(Boolean).join("|"));

const UPSTREAM = "origin/main";

/** Whether HEAD sits on the commit where the base left the upstream and holds every base commit the upstream lacks, none of them a merge: by patch-id, or as a fold, a fork commit with its subject that changes all its files. */
async function rebasedOntoUpstream(checkout: string, base: string): Promise<boolean> {
	const forkPoint = await git(checkout, "merge-base", base, UPSTREAM);
	if (forkPoint.code || (await git(checkout, "merge-base", "--is-ancestor", forkPoint.out.trim(), "HEAD")).code) return false;
	if (await gitOut(checkout, "rev-list", "--merges", "-n1", base, "^HEAD", `^${UPSTREAM}`)) return false;
	const cherry = await git(checkout, "cherry", "HEAD", base, UPSTREAM);
	const missing = cherry.out.split("\n").filter((line) => line.startsWith("+ ")).map((line) => line.slice(2));
	if (cherry.code || !missing.length) return cherry.code === 0;
	const forkCommits = (await gitOut(checkout, "log", "--format=%H", `${UPSTREAM}..HEAD`)).split("\n").filter(Boolean);
	const folds = await Promise.all(forkCommits.map(async (sha) => ({ subject: await subjectOf(checkout, sha), files: new Set(await filesOf(checkout, sha)) })));
	for (const sha of missing) {
		const [subject, files] = [await subjectOf(checkout, sha), await filesOf(checkout, sha)];
		if (!folds.some((fold) => fold.subject === subject && files.every((file) => fold.files.has(file)))) return false;
	}
	return true;
}

const subjectOf = (checkout: string, sha: string) => gitOut(checkout, "log", "-1", "--format=%s", sha);
/** The files a commit changes. */
const filesOf = async (checkout: string, sha: string) => (await gitOut(checkout, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha)).split("\n").filter(Boolean);

/** The commit after which the fork's own commits start: its base, or the upstream when the fork rewrote the base's commits. */
async function landFrom(tree: Worktree): Promise<string | undefined> {
	const checkout = checkoutOf(tree);
	if ((await git(checkout, "merge-base", "--is-ancestor", tree.base, "HEAD")).code === 0) return tree.base;
	return (await rebasedOntoUpstream(checkout, tree.base)) ? UPSTREAM : undefined;
}

/** Returns why the fork's commits may not land on its base, or undefined when they may. */
export async function refusal(tree: Worktree, extraNames?: string): Promise<string | undefined> {
	const off = await offBranch(tree);
	if (off) return off;
	const checkout = checkoutOf(tree);
	if ((await gitOut(checkout, "status", "--porcelain")) !== "") return "the worktree has uncommitted changes";
	const from = await landFrom(tree);
	if (!from) return `the commits do not sit on the current ${tree.base}; rebase them onto it`;
	const range = `${from}..HEAD`;
	if (FOLD_PREFIX.test(await gitOut(checkout, "log", "--format=%s", range))) return "a fixup!, squash! or amend! commit is left; autosquash it first";
	const names = privateNames(extraNames);
	if (names.test(await gitOut(checkout, "log", "-p", "--format=%B", range))) return `the commits name a private path or name matching ${names.source}`;
	if ((await mainSnapshot(tree.repo)) !== tree.snapshot) return "the main checkout changed during the fork";
	return undefined;
}

const hasBranch = async (tree: Worktree) => (await git(tree.repo, "rev-parse", "--verify", "--quiet", `refs/heads/${tree.branch}`)).code === 0;

/** Has the worktree provider remove a worktree it made. */
async function removeProvided(dir: string): Promise<Ran> {
	const remover = provider();
	if (!remover) return { code: 1, out: `no worktree provider to remove ${dir}` };
	try {
		await remover.remove(dir);
		return { code: 0, out: "" };
	} catch (error) {
		return { code: 1, out: error instanceof Error ? error.message : String(error) };
	}
}

/** Removes the landed worktree and branch, and says what stayed. The branch is deleted without a merge check when `pushed`, as a remote branch holds its commits. */
async function cleanup(tree: Worktree, pushed = false): Promise<string | undefined> {
	const removed = tree.provided ? await removeProvided(tree.path) : await git(tree.repo, "worktree", "remove", "--force", tree.path);
	const deleted = (await hasBranch(tree)) ? await git(tree.repo, "branch", pushed ? "-D" : "-d", tree.branch) : { code: 0, out: "" };
	const failed = [removed, deleted].filter(({ code }) => code).map(({ out }) => out.trim());
	return failed.length ? `cleanup left files: ${failed.join("; ")}` : undefined;
}

const CONTEXT_FILES = /^\?\? \.context(\/|$)/;

/** Whether every commit of the fork branch is on `PUSH_REMOTE`: on one of its branches, or with its patch in `UPSTREAM`. A failed fetch trusts none. */
async function onRemote(tree: Worktree): Promise<boolean> {
	const checkout = checkoutOf(tree);
	if ((await offBranch(tree)) || (await git(checkout, "fetch", "-q", "--prune", PUSH_REMOTE)).code) return false;
	const unpushed = await git(checkout, "rev-list", "--count", "HEAD", "--not", `--remotes=${PUSH_REMOTE}`);
	if (unpushed.code === 0 && unpushed.out.trim() === "0") return true;
	const cherry = await git(checkout, "cherry", UPSTREAM, "HEAD");
	return cherry.code === 0 && !/^\+ /m.test(cherry.out);
}

/** Removes the worktree and its branch when the fork left no changes besides untracked `.context` files, and every commit in it is on the remote. */
export async function dropIfClean(tree: Worktree): Promise<boolean> {
	if (!fs.existsSync(tree.path)) return false;
	const status = await git(checkoutOf(tree), "status", "--porcelain");
	const ahead = await git(checkoutOf(tree), "rev-list", "--count", `${tree.base}..HEAD`);
	if (status.code || ahead.code || status.out.split("\n").some((line) => line && !CONTEXT_FILES.test(line))) return false;
	const committed = ahead.out.trim() !== "0";
	if (committed && !(await onRemote(tree))) return false;
	return (await cleanup(tree, committed)) === undefined;
}

/** Makes the git worktree again on its branch, or on a new branch from its base, when it is gone. */
export async function restoreWorktree(tree: Worktree): Promise<void> {
	if (fs.existsSync(tree.path)) return;
	if (tree.provided) throw new Error(`the worktree ${tree.path} is gone`);
	await git(tree.repo, "worktree", "prune");
	if (tree.own) await git(tree.repo, "fetch", "-q", PUSH_REMOTE);
	const remote = `refs/remotes/${PUSH_REMOTE}/${tree.branch}`;
	const from = tree.own && (await git(tree.repo, "rev-parse", "--verify", "--quiet", remote)).code === 0 ? remote : tree.base;
	if (await hasBranch(tree)) await gitOut(tree.repo, "worktree", "add", tree.path, tree.branch);
	else await addBranchWorktree(tree.repo, tree.path, tree.branch, from, Boolean(tree.own));
}

/** The worktree a continued run works in: the kept one, or a new one when it is gone. */
export async function resumeWorktree(tree: Worktree, root: string, name: string): Promise<Worktree> {
	if (tree.own) {
		await restoreWorktree(tree);
		return { ...tree, snapshot: await mainSnapshot(tree.repo) };
	}
	return fs.existsSync(tree.path) ? { ...tree, snapshot: await mainSnapshot(tree.repo) } : createWorktree(tree.repo, root, name);
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
	/** What the fork's reply amounts to. */
	first: Event;
	/** Regex of private names, besides the home directory path, that must not land. */
	privateNames?: string;
	/** Once aborted, nothing more lands. */
	signal?: AbortSignal;
	/** Rebases the fork's commits onto the base inside the landing queue when the base moved. A rebase that conflicts is undone. */
	rebase?: boolean;
}

/** Rebases the fork's clean worktree onto its base, and leaves it as it was when the base no longer descends from the commit the fork started at, or the rebase conflicts. */
async function rebaseOntoBase(tree: Worktree): Promise<void> {
	const checkout = checkoutOf(tree);
	if (!tree.start || (await git(checkout, "merge-base", "--is-ancestor", tree.start, tree.base)).code || (await offBranch(tree)) || (await gitOut(checkout, "status", "--porcelain")) !== "" || (await landFrom(tree))) return;
	if ((await git(checkout, "rebase", "-q", tree.base)).code) await git(checkout, "rebase", "--abort");
}

const CANCELLED = "cancelled before landing";

/** The remote branch other than the base that holds the fork branch's tip, when the worktree is on that branch, clean, and has commits past the base. Only refs of `PUSH_REMOTE` count, and a failed fetch trusts none. */
async function pushedTo(tree: Worktree): Promise<string | undefined> {
	const checkout = checkoutOf(tree);
	if ((await offBranch(tree)) || (await gitOut(checkout, "status", "--porcelain")) !== "" || (await gitOut(checkout, "rev-list", "--count", `${tree.base}..${tree.branch}`)) === "0") return undefined;
	if ((await git(checkout, "fetch", "-q", "--prune", PUSH_REMOTE)).code) return undefined;
	const contains = await git(checkout, "branch", "-r", "--list", `${PUSH_REMOTE}/*`, "--contains", `refs/heads/${tree.branch}`, "--format=%(refname:short)");
	return contains.out.split("\n").find((name) => name && !name.endsWith("/HEAD") && !name.endsWith(`/${tree.base}`));
}

async function landNow({ tree, first, privateNames: extraNames, signal, rebase }: LandOptions): Promise<Landing> {
	const escalate = async (reason: string): Promise<Landing> => ({ state: "escalated", reason, removed: await dropIfClean(tree) });
	if (signal?.aborted) return escalate(CANCELLED);
	if (first.type === "fork-failed") return escalate(`fork failed: ${first.reason}`);
	if (first.type === "fork-blocked") return escalate(`fork is blocked: ${first.reason}`);
	const pushed = await pushedTo(tree);
	if (signal?.aborted) return escalate(CANCELLED);
	if (pushed) return { state: "landed", sha: await gitOut(checkoutOf(tree), "rev-parse", tree.branch), note: [`landed on ${pushed} by push`, await cleanup(tree, true)].filter(Boolean).join("; ") };
	if (tree.own) return (await gitOut(checkoutOf(tree), "rev-list", "--count", `${tree.base}..HEAD`)) === "0" ? { state: "landed", note: await cleanup(tree) } : escalate(`${tree.branch} was not pushed`);
	if (rebase) await rebaseOntoBase(tree);
	const reason = await refusal(tree, extraNames);
	if (reason) return escalate(reason);
	const checkout = checkoutOf(tree);
	if ((await gitOut(checkout, "rev-list", "--count", `${tree.base}..HEAD`)) === "0") return { state: "landed", note: await cleanup(tree) };
	if (signal?.aborted) return escalate(CANCELLED);
	const fetched = await run("git", ["fetch", "-q", checkout, "HEAD"], tree.repo, signal);
	if (fetched.code) return escalate(`could not fetch ${tree.branch} from ${checkout}: ${fetched.out.trim()}`);
	const rebased = (await landFrom(tree)) !== tree.base;
	if (signal?.aborted) return escalate(CANCELLED);
	const merged = await git(tree.repo, ...(rebased ? ["reset", "-q", "--keep", "FETCH_HEAD"] : ["merge", "--ff-only", "-q", "FETCH_HEAD"]));
	if (merged.code) return escalate(`${tree.base} moved during the fork; land ${tree.branch} by hand`);
	return { state: "landed", sha: await gitOut(tree.repo, "rev-parse", "HEAD"), note: await cleanup(tree) };
}

const queues = new Map<string, Promise<unknown>>();

/** Lands the worktree's commits on its main checkout, one landing at a time per checkout. Never pushes. */
export function land(options: LandOptions): Promise<Landing> {
	const key = fs.realpathSync(options.tree.repo);
	const landing = (queues.get(key) ?? Promise.resolve()).then(() => landNow(options));
	queues.set(key, landing.then(undefined, () => undefined));
	return landing;
}
