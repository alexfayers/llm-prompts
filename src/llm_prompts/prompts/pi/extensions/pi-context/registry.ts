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
	ref?: string;
	worktree?: string;
	branch?: string;
	startedAt: number;
	endedAt?: number;
};

const LIVE: RunState[] = ["running", "landing"];

export class Registry {
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

	all(): Run[] {
		return [...this.runs.values()];
	}

	live(): Run[] {
		return this.all().filter((run) => LIVE.includes(run.state));
	}

	onChange(listener: (run: Run) => void): () => void {
		this.listeners.add(listener);
		return () => void this.listeners.delete(listener);
	}

	/** Builds a registry from saved run records: the last record of a run wins, and a run still live in it is lost. */
	static rebuild(records: Run[]): Registry {
		const registry = new Registry();
		for (const record of records) registry.runs.set(record.id, { ...record });
		for (const run of registry.runs.values()) if (LIVE.includes(run.state)) run.state = "lost";
		return registry;
	}

	private notify(run: Run) {
		for (const listener of this.listeners) listener(run);
	}
}

const KEY = Symbol.for("pi-context.registry");

export function registryOf(): Registry {
	const holder = globalThis as { [KEY]?: Registry };
	return (holder[KEY] ??= new Registry());
}
