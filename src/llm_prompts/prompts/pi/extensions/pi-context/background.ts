// Tracks background fork runs: wakes the main session when one finishes, delivers results that arrive during a run when it settles and holds a session without a UI until they finish.
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { isLive, registryOf, type Registry, type Run } from "./registry.ts";
import type { LiveView, Watchable } from "./live-view.ts";
import { openAsks, resolveAsk } from "../pending-asks.ts";
import { askUserUnanswered, digestLine, openForkAsks, pinForkAsks, wakeReason } from "./wake.ts";

export const RESULTS_TYPE = "pi-context-results";

type AskContext = Pick<ExtensionContext, "hasUI" | "ui" | "sessionManager">;
type Steerable = Watchable & { steer(text: string): Promise<string | undefined> };
const MAX_HOLD_MS = 2 * 60 * 60 * 1000;

export class Background {
	private controllers = new Map<string, AbortController>();
	private children = new Map<string, Steerable>();
	private holding = false;
	/** Fork-ask pins not yet announced to main. */
	private pinned: string[] = [];
	/** Fork-ask pins announced in the current main run, cleared when it settles unless an `ask_user` went unanswered. */
	private announced: string[] = [];
	private askUnanswered = false;
	private pi: Pick<ExtensionAPI, "sendMessage" | "appendEntry">;
	private registry: Registry;
	/** Shows the run's activity in the UI once its child is attached. */
	view: LiveView | undefined;

	constructor(pi: Pick<ExtensionAPI, "sendMessage" | "appendEntry">, registry: Registry = registryOf()) {
		this.pi = pi;
		this.registry = registry;
	}

	/** The signal that stops the background run. */
	track(runId: string): AbortSignal {
		const controller = new AbortController();
		this.controllers.set(runId, controller);
		return controller.signal;
	}

	/** Lets `steer` reach the run's child. */
	attach(runId: string, child: Steerable): void {
		this.children.set(runId, child);
		this.view?.watch(runId, child);
	}

	/** Sends a steering message to a live background run by name. */
	async steer(name: string, message: string): Promise<void> {
		const live = this.registry.live().filter((run) => run.background);
		const run = live.find((candidate) => candidate.name === name);
		const child = run && this.children.get(run.id);
		if (!child) throw new Error(`no live background fork ${name}. Live forks: ${live.map((candidate) => candidate.name).join(", ") || "none"}`);
		const refused = await child.steer(message);
		if (refused) throw new Error(`fork ${name} did not take the message: ${refused}`);
	}

	/** Records how a background run ended, pins what it asks, and wakes main. A cancelled run is ignored. */
	finish(ctx: Pick<ExtensionContext, "isIdle"> & AskContext, runId: string, patch: Partial<Run>, text: string, note?: string): void {
		this.controllers.delete(runId);
		this.children.delete(runId);
		const current = this.registry.get(runId);
		if (!current || !isLive(current)) return;
		const held = this.holding;
		const ended = { ...current, ...patch, endedAt: Date.now() };
		const run = this.registry.update(runId, { ...ended, unread: digestLine(ended, text, note) });
		if (!run) return;
		this.pinned.push(...pinForkAsks(this.pi, ctx, run, text));
		if (wakeReason(run) && !held) this.wake(ctx);
	}

	/** Stops a live background run by name. */
	cancel(name: string): Run | undefined {
		const run = this.registry.live().find((live) => live.background && live.name === name);
		if (!run) return undefined;
		this.controllers.get(run.id)?.abort();
		this.controllers.delete(run.id);
		this.children.delete(run.id);
		return this.registry.update(run.id, { state: "cancelled", endedAt: Date.now() });
	}

	/** The digest lines of the runs that finished since main last read them, with the pins they made, or undefined. */
	digest(): string | undefined {
		const unread = this.registry.all().filter((run) => run.unread).sort((a, b) => (a.endedAt ?? 0) - (b.endedAt ?? 0));
		if (!unread.length) return undefined;
		const lines = unread.map((run) => run.unread!);
		for (const run of unread) this.registry.update(run.id, { unread: undefined });
		const pins = this.pinned.splice(0);
		this.announced.push(...pins);
		if (pins.length) lines.push(`Pinned: ${pins.join(", ")}. They clear at the end of this turn unless you put them to the user with ask_user.`);
		return lines.join("\n");
	}

	/** Notes whether an `ask_user` call of a main run went unanswered. */
	noteRun(messages: Parameters<typeof askUserUnanswered>[0]): void {
		this.askUnanswered ||= askUserUnanswered(messages);
	}

	/** Resolves the pins announced in the main run that settled, unless it was aborted or an `ask_user` call went unanswered. */
	settleAsks(ctx: AskContext, aborted: boolean): void {
		const ids = this.announced.splice(0);
		const keep = aborted || this.askUnanswered;
		this.askUnanswered = false;
		if (keep) return;
		const open = new Set(openAsks(ctx.sessionManager.getBranch() as Parameters<typeof openAsks>[0]).map((ask) => ask.id));
		for (const id of ids) if (open.has(id)) resolveAsk(this.pi, ctx, id);
	}

	/** Resolves a fork's open pins, once main resumes or steers it with the answer. */
	resolveForkAsks(ctx: AskContext, name: string): void {
		const entries = ctx.sessionManager.getBranch() as Parameters<typeof openAsks>[0];
		for (const run of this.registry.all().filter((candidate) => candidate.name === name)) for (const id of openForkAsks(entries, run)) resolveAsk(this.pi, ctx, id);
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
			this.children.delete(run.id);
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

const lostNote = ({ endedBy, worktree, task, files, name }: Run) =>
	`${endedBy === "reload" ? "a /reload ended it" : "its session ended"} before it finished.${worktree ? ` Its worktree ${worktree} is kept.` : ""}${files ? ` fork_resume ${name} continues it.` : ""} Task: ${task}`;

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

	pi.on("agent_end", (event) => background.noteRun(event.messages));

	pi.on("agent_settled", (event, ctx) => {
		background.settleAsks(ctx, event.aborted);
	});

	pi.on("agent_before_settle", async (event, ctx) => {
		if (!ctx.hasUI) await background.hold();
		const content = background.digest();
		if (!content) return undefined;
		return { entries: [...event.entries, { type: "custom_message" as const, customType: RESULTS_TYPE, content, display: true }], continue: true };
	});
}
