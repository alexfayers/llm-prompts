// Keeps the state of every fork run, shared by the extensions of one pi process.
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
	startedAt: number;
	endedAt?: number;
	/** Why the session that ran it ended while it was live. */
	endedBy?: string;
};

const LIVE: RunState[] = ["running", "landing"];

export const isLive = (run: Run): boolean => LIVE.includes(run.state);

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

	/** Replaces the runs with saved records, where the last record of a run wins. Returns the runs that were still live in them, now lost. */
	restore(records: Run[]): Run[] {
		this.runs.clear();
		for (const record of records) this.runs.set(record.id, { ...record });
		const lost = this.live();
		for (const run of lost) run.state = "lost";
		return lost;
	}

	static rebuild(records: Run[]): Registry {
		const registry = new Registry();
		registry.restore(records);
		return registry;
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
