// Keeps the state of every fork run, shared by the extensions of one pi process.
import fs from "node:fs";
import path from "node:path";
import { cacheLifetimeMs } from "../context-fold.ts";

export type RunState = "running" | "landing" | "done" | "found-it" | "blocked" | "failed" | "lost" | "cancelled";

export type Run = {
	id: string;
	name: string;
	role: string;
	background: boolean;
	state: RunState;
	task: string;
	outcome?: string;
	notify?: boolean;
	ref?: string;
	worktree?: string;
	branch?: string;
	/** A writer's worktree, as the landing needs it. */
	tree?: { repo: string; path: string; branch: string; own?: boolean; base: string; snapshot: string };
	/** The git checkout the delegate works in, when it is not the session's directory. */
	target?: string;
	/** The session's directory when the run started. */
	cwd?: string;
	/** The directory of the delegate's seed, handshake and session files. */
	files?: string;
	/** The name of the fork that began the prompt cache group it joined by starting from a finished fork's session. */
	from?: string;
	/** The prompt cache key its requests send when it joined such a group. */
	cacheKey?: string;
	/** The model of a cold worker. */
	model?: string;
	startedAt: number;
	endedAt?: number;
	/** When the delegate's last model request ended, which starts its prompt cache's lifetime. */
	lastRequestAt?: number;
	/** The context size of the delegate's last request, in tokens. */
	context?: number;
	/** What a fork waiting for a free slot starts with, so `fork_resume` can start it after a reload. */
	queued?: { message: string; resume: boolean };
	/** The digest lines of its results that main has not read yet, one per line. */
	unread?: string;
	/** Why the session that ran it ended while it was live. */
	endedBy?: string;
};

const LIVE: RunState[] = ["running", "landing"];

export const isLive = (run: Run): boolean => LIVE.includes(run.state);

export const FINISHED: RunState[] = ["done", "found-it", "blocked", "failed"];

/** The milliseconds a finished run's prompt cache has left, 0 once expired, or undefined without a recorded request. */
export const cacheLeftMs = (run: Run, now = Date.now()): number | undefined => (run.lastRequestAt === undefined ? undefined : Math.max(0, run.lastRequestAt + cacheLifetimeMs() - now));

export const cacheText = (left: number): string => (left > 0 ? `cache ${Math.ceil(left / 60_000)}m left` : "cache expired");

/** The session file a run's delegate wrote: the seed of a warm fork, or the newest session of a cold worker. */
export function sessionFileOf(files: string, cold: boolean): string | undefined {
	if (!cold) return fs.existsSync(path.join(files, "seed.jsonl")) ? path.join(files, "seed.jsonl") : undefined;
	const sessions = path.join(files, "session");
	if (!fs.existsSync(sessions)) return undefined;
	const found = fs.readdirSync(sessions, { recursive: true, encoding: "utf8" }).filter((file) => file.endsWith(".jsonl")).map((file) => path.join(sessions, file));
	return found.sort((a, b) => fs.statSync(a).mtimeMs - fs.statSync(b).mtimeMs).at(-1);
}

const REGISTRY_VERSION = 1;

export class Registry {
	readonly version = REGISTRY_VERSION;
	private runs = new Map<string, Run>();
	private listeners = new Set<(run: Run) => void>();

	start(run: Run): Run {
		this.runs.set(run.id, run);
		this.notify(run);
		return run;
	}

	update(id: string, patch: Partial<Run>): Run | undefined {
		const run = this.runs.get(id);
		if (!run) return undefined;
		Object.assign(run, patch);
		this.notify(run);
		return run;
	}

	get(id: string): Run | undefined {
		return this.runs.get(id);
	}

	all(): Run[] {
		return [...this.runs.values()];
	}

	live(): Run[] {
		return this.all().filter(isLive);
	}

	onChange(listener: (run: Run) => void): () => void {
		this.listeners.add(listener);
		return () => void this.listeners.delete(listener);
	}

	/** Replaces the runs with the saved records that `keep` accepts once the live ones are lost, where the last record of a run wins. Returns the runs that were still live in them, now lost. */
	restore(records: Run[], keep: (run: Run) => boolean = () => true): Run[] {
		this.runs.clear();
		for (const record of records) this.runs.set(record.id, { ...record });
		const lost = this.live();
		for (const run of lost) run.state = "lost";
		for (const run of this.all()) if (!keep(run)) this.runs.delete(run.id);
		return lost;
	}

	private notify(run: Run) {
		for (const listener of this.listeners) listener(run);
	}
}

const KEY = Symbol.for("pi-context.registry");

export function registryOf(): Registry {
	const holder = globalThis as { [KEY]?: Registry };
	const existing = holder[KEY];
	return existing?.version === REGISTRY_VERSION ? existing : (holder[KEY] = new Registry());
}

/** The registry when pi-context is loaded, without creating one. */
export const forkRegistry = (): Registry | undefined => (globalThis as { [KEY]?: Registry })[KEY];
