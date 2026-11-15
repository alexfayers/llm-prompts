// Tracks background fork runs: wakes the main session when one finishes, delivers results that arrive during a run when it settles and holds a session without a UI until they finish.
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { isLive, registryOf, type Registry, type Run } from "./registry.ts";
import { Coalescer, digestLine, wakeReason } from "./wake.ts";

export const RESULTS_TYPE = "pi-context-results";
const MAX_HOLD_MS = 2 * 60 * 60 * 1000;

export class Background {
	private controllers = new Map<string, AbortController>();
	private coalescer = new Coalescer();
	private holding = false;
	private pi: Pick<ExtensionAPI, "sendMessage">;
	private registry: Registry;

	constructor(pi: Pick<ExtensionAPI, "sendMessage">, registry: Registry = registryOf()) {
		this.pi = pi;
		this.registry = registry;
	}

	/** The signal that stops the background run. */
	track(runId: string): AbortSignal {
		const controller = new AbortController();
		this.controllers.set(runId, controller);
		return controller.signal;
	}

	/** Records how a background run ended, and wakes main. A cancelled run is ignored. */
	finish(ctx: Pick<ExtensionContext, "isIdle">, runId: string, patch: Partial<Run>, text: string, note?: string): void {
		this.controllers.delete(runId);
		const current = this.registry.get(runId);
		if (!current || !isLive(current)) return;
		const held = this.holding;
		const run = this.registry.update(runId, { ...patch, endedAt: Date.now() });
		if (!run) return;
		this.coalescer.add(run, text, note);
		if (wakeReason(run) && !held) this.wake(ctx);
	}

	/** Stops a live background run by name. */
	cancel(name: string): Run | undefined {
		const run = this.registry.live().find((live) => live.background && live.name === name);
		if (!run) return undefined;
		this.controllers.get(run.id)?.abort();
		this.controllers.delete(run.id);
		return this.registry.update(run.id, { state: "cancelled", endedAt: Date.now() });
	}

	/** The digest lines of the runs that finished since main last read them, or undefined. */
	digest(): string | undefined {
		return this.coalescer.take().join("\n") || undefined;
	}

	/** Waits until no run is live or one needs main, or `maxMs` has passed. */
	hold(maxMs = MAX_HOLD_MS): Promise<void> {
		if (!this.registry.live().length) return Promise.resolve();
		this.holding = true;
		return new Promise<void>((resolve) => {
			const release = () => {
				off();
				clearTimeout(timer);
				this.holding = false;
				resolve();
			};
			const off = this.registry.onChange((run) => {
				if (this.registry.live().length && !wakeReason(run)) return;
				release();
			});
			const timer = setTimeout(release, maxMs);
			timer.unref();
		});
	}

	/** Stops every live background run and marks it lost, so the next session reports it. */
	shutdown(): void {
		for (const run of this.registry.live()) {
			if (!run.background) continue;
			this.controllers.get(run.id)?.abort();
			this.controllers.delete(run.id);
			this.registry.update(run.id, { state: "lost", endedAt: Date.now() });
		}
	}

	/** Starts a turn with the digest when main is idle. A busy main gets it when its run settles. */
	private wake(ctx: Pick<ExtensionContext, "isIdle">) {
		if (!ctx.isIdle()) return;
		const content = this.digest();
		if (content) this.pi.sendMessage({ customType: RESULTS_TYPE, content, display: true }, { triggerTurn: true });
	}
}

const RUN_TYPE = "pi-context-run";

const lostNote = ({ endedBy, worktree, task }: Run) =>
	`${endedBy === "reload" ? "a /reload ended it" : "its session ended"} before it finished.${worktree ? ` Its worktree ${worktree} is kept.` : ""} Task: ${task}`;

/** Hooks that deliver the digest, hold a session without a UI, and save and restore the runs across sessions. */
export function registerBackgroundHooks(pi: ExtensionAPI, background: Background, registry: Registry = registryOf()) {
	let stopSaving: (() => void) | undefined;
	const save = (run: Run) => {
		if (!run.background) return;
		try {
			pi.appendEntry(RUN_TYPE, { ...run });
		} catch {
			stopSaving?.();
			stopSaving = undefined;
		}
	};

	pi.on("session_start", (_event, ctx) => {
		stopSaving?.();
		const saved = ctx.sessionManager.getEntries().flatMap((entry) => (entry.type === "custom" && entry.customType === RUN_TYPE ? [entry.data as Run] : []));
		for (const run of registry.restore(saved)) {
			save(run);
			pi.sendMessage({ customType: RESULTS_TYPE, content: digestLine(run, lostNote(run)), display: true }, { deliverAs: "nextTurn" });
		}
		stopSaving = registry.onChange(save);
	});

	pi.on("session_shutdown", ({ reason }) => {
		for (const run of registry.live()) if (run.background) registry.update(run.id, { endedBy: reason });
		stopSaving?.();
		stopSaving = undefined;
		background.shutdown();
	});

	pi.on("before_agent_start", () => {
		const content = background.digest();
		return content ? { message: { customType: RESULTS_TYPE, content, display: true } } : undefined;
	});

	pi.on("agent_before_settle", async (event, ctx) => {
		if (!ctx.hasUI) await background.hold();
		const content = background.digest();
		if (!content) return undefined;
		return { entries: [...event.entries, { type: "custom_message" as const, customType: RESULTS_TYPE, content, display: true }], continue: true };
	});
}
