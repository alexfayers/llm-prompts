// Tracks background fork runs: wakes the main session when one finishes, delivers results that arrive during a run when it settles, holds a session without a UI until they finish and notes a fork that runs long.
// Config: llmPrompts.forks.checkInMinutes in pi settings (minutes a fork runs before the next tool result names it, default 5; 0 turns the note off)
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { canResume, isLive, isOwnRun, registryOf, reloadRequested, sessionFileOf, type Registry, type Run } from "./registry.ts";
import type { LiveView, Watchable } from "./live-view.ts";
import { openAsks, resolveAsk } from "../pending-asks.ts";
import type { Reply } from "./reply.ts";
import { isTeam } from "./roles.ts";
import { askPrefix, askUserUnanswered, digestLine, openForkAsks, pinForkAsks, wakeReason } from "./wake.ts";

export const RESULTS_TYPE = "pi-context-results";

type AskContext = Pick<ExtensionContext, "hasUI" | "ui" | "sessionManager">;
type Steerable = Watchable & { steer(text: string): Promise<string | undefined> };
const MAX_HOLD_MS = 2 * 60 * 60 * 1000;
const MINUTE_MS = 60_000;
const DEFAULT_CHECK_IN_MINUTES = 5;

/** Lets at most `limit()` jobs run at once: the rest wait in order and start as a running one ends. */
export class Slots {
	private active = 0;
	private waiting: (() => void)[] = [];

	private limit: () => number;

	constructor(limit: () => number) {
		this.limit = limit;
	}

	/** The jobs that run now. */
	get live(): number {
		return this.active;
	}

	/** Whether a job started now would have to wait. */
	get full(): boolean {
		return this.active >= this.limit();
	}

	/** Runs `job` once a slot is free, or at once with `immediate`, which still takes a slot so later jobs wait for it. A `signal` that aborts while the job waits rejects it without starting it. */
	async run<T>(job: () => Promise<T>, signal?: AbortSignal, immediate = false): Promise<T> {
		if (this.full && !immediate) {
			await new Promise<void>((resolve, reject) => {
				const start = () => {
					signal?.removeEventListener("abort", leave);
					this.active++;
					resolve();
				};
				const leave = () => {
					this.waiting.splice(this.waiting.indexOf(start), 1);
					reject(signal?.reason);
				};
				this.waiting.push(start);
				signal?.addEventListener("abort", leave, { once: true });
			});
		} else this.active++;
		try {
			return await job();
		} finally {
			this.active--;
			if (!this.full) this.waiting.shift()?.();
		}
	}
}

export class Background {
	private controllers = new Map<string, AbortController>();
	private children = new Map<string, Steerable>();
	private holding = false;
	/** Fork-ask pins not yet announced to main. */
	private pinned: string[] = [];
	/** Fork-ask pins announced in the current main run, cleared when it settles unless an `ask_user` went unanswered. */
	private announced: string[] = [];
	private askUnanswered = false;
	/** Each started run's end, once its delegate has stopped and its landing is over. */
	private following = new Map<string, Promise<unknown>>();
	/** Ends the wait of `hold`, while one is running. */
	private releaseHold: (() => void) | undefined;
	/** Whether the latest run ended aborted or in an error. */
	private runFailed = false;
	/** The unread line of each run in a digest main has received but not yet settled on. */
	private delivered = new Map<string, string>();
	/** When each live fork was last noted as running long. */
	private checkedInAt = new Map<string, number>();
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

	/** Lets `shutdown` wait until the run has ended. */
	follow(runId: string, running: Promise<unknown>): void {
		const ended = running.then(undefined, () => undefined).finally(() => this.following.delete(runId));
		this.following.set(runId, ended);
	}

	/** Settles once the run's delegate, with its cleanup and landing, has ended. */
	ended(runId: string): Promise<unknown> | undefined {
		return this.following.get(runId);
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
	finish(ctx: Pick<ExtensionContext, "isIdle"> & AskContext, runId: string, patch: Partial<Run>, text: string | Reply, note?: string): void {
		this.controllers.delete(runId);
		this.children.delete(runId);
		const current = this.registry.get(runId);
		if (!current || !isLive(current)) return;
		const held = this.holding;
		const ended = { ...current, ...patch, endedAt: Date.now() };
		const run = this.registry.update(runId, { ...ended, unread: [current.unread, digestLine(ended, text, note)].filter(Boolean).join("\n") });
		if (!run) return;
		this.pinned.push(...pinForkAsks(this.pi, ctx, run, text));
		if (wakeReason(run) && !held) this.wake(ctx);
	}

	/** Stops a live background run by name. */
	cancel(name: string): Run | undefined {
		return this.cancelRun(this.registry.live().find((live) => live.background && live.name === name)?.id);
	}

	/** Stops a live background run by id. */
	cancelRun(runId: string | undefined): Run | undefined {
		const run = runId && this.registry.live().find((live) => live.background && live.id === runId);
		if (!run) return undefined;
		this.controllers.get(run.id)?.abort();
		this.controllers.delete(run.id);
		this.children.delete(run.id);
		return this.registry.update(run.id, { state: "cancelled", endedAt: Date.now() });
	}

	/** The digest lines of the runs that finished since main last received them, with the pins they made, or undefined. A line stays unread until the run that received it settles. */
	digest(): string | undefined {
		const unread = this.registry.all().filter((run) => run.unread && this.delivered.get(run.id) !== run.unread).sort((a, b) => (a.endedAt ?? 0) - (b.endedAt ?? 0));
		if (!unread.length) return undefined;
		const lines = unread.map((run) => run.unread!);
		for (const run of unread) this.delivered.set(run.id, run.unread!);
		this.view?.refresh();
		const pins = this.pinned.splice(0);
		this.announced.push(...pins);
		if (pins.length) lines.push(`Pinned: ${pins.join(", ")}. They clear at the end of this turn unless you put them to the user with ask_user.`);
		return lines.join("\n");
	}

	/** One line per live fork that ran `intervalMs` since it started or was last noted, with its turns and last tool call. A fork with an `llm-prompts watch` call still running is skipped. Undefined when none. */
	checkIns(intervalMs: number, now = Date.now()): string | undefined {
		const live = this.registry.live().filter((run) => run.background);
		for (const id of this.checkedInAt.keys()) if (!live.some((run) => run.id === id)) this.checkedInAt.delete(id);
		const lines = live.flatMap((run) => {
			const { turns, lastCall, watching } = this.view?.progress(run.id) ?? { turns: 0, watching: false };
			if (watching || now - (this.checkedInAt.get(run.id) ?? run.startedAt) < intervalMs) return [];
			this.checkedInAt.set(run.id, now);
			const last = lastCall ? `, last call ${lastCall}` : "";
			return [`[fork ${run.name}] still running after ${Math.floor((now - run.startedAt) / MINUTE_MS)}m, ${turns} turn${turns === 1 ? "" : "s"}${last}. Check on it with fork_steer, or stop it with fork_cancel.`];
		});
		return lines.length ? lines.join("\n") : undefined;
	}

	/** Whether main has received the run's current unread lines. */
	received(run: Run): boolean {
		return Boolean(run.unread) && this.delivered.get(run.id) === run.unread;
	}

	/** Notes whether an `ask_user` call of a main run went unanswered, and whether the run ended in an error. */
	noteRun(messages: (Parameters<typeof askUserUnanswered>[0][number] & { stopReason?: string })[]): void {
		this.askUnanswered ||= askUserUnanswered(messages);
		this.runFailed = ["error", "aborted"].includes(messages.filter((message) => message.role === "assistant").at(-1)?.stopReason ?? "");
	}

	/** Once the main run settles, marks the results it received as read and resolves the pins announced in it, unless it was aborted or failed, when the next digest announces them again. A pin also stays while an `ask_user` call went unanswered. */
	settle(ctx: AskContext, aborted: boolean): void {
		const ids = this.announced.splice(0);
		const failed = aborted || this.runFailed;
		const keep = failed || this.askUnanswered;
		this.askUnanswered = false;
		for (const [id, line] of this.delivered) if (!failed && this.registry.get(id)?.unread === line) this.registry.update(id, { unread: undefined });
		this.delivered.clear();
		this.view?.refresh();
		if (failed) this.pinned.unshift(...ids);
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
				this.releaseHold = undefined;
				resolve();
			};
			const off = this.registry.onChange((run) => {
				if (this.registry.live().length && !wakeReason(run)) return;
				release();
			});
			const timer = setTimeout(release, maxMs);
			timer.unref();
			this.releaseHold = release;
		});
	}

	/** Stops every live background run and marks it lost, so the next session reports it, releases the wait of `hold`, and resolves once every run has ended. */
	async shutdown(): Promise<void> {
		for (const run of this.registry.live()) {
			if (!run.background) continue;
			this.controllers.get(run.id)?.abort();
			this.controllers.delete(run.id);
			this.children.delete(run.id);
			this.registry.update(run.id, { state: "lost", endedAt: Date.now() });
		}
		this.releaseHold?.();
		await Promise.all(this.following.values());
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

/** Whether a restored run is still needed: unread, asking, or with files a `fork_resume` continues from. */
const isRetained = (run: Run, askIds: string[]): boolean =>
	run.background && (isLive(run) || Boolean(run.unread || run.queued) || askIds.some((id) => id.startsWith(askPrefix(run))) || Boolean(run.files && sessionFileOf(run.files, Boolean(run.model))));

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

	pi.on("session_start", (event, ctx) => {
		stopSaving?.();
		const entries = ctx.sessionManager.getEntries();
		const latest = new Map<string, Run>();
		for (const entry of entries) if (entry.type === "custom" && entry.customType === RUN_TYPE && isOwnRun(entry.data as Run)) latest.set((entry.data as Run).id, entry.data as Run);
		const askIds = openAsks(entries as Parameters<typeof openAsks>[0]).map((ask) => ask.id);
		const lost = registry.restore([...latest.values()], (run) => isRetained(run, askIds));
		for (const run of lost) {
			save(run);
			if (event.reason === "reload" && reloadRequested() && run.endedBy === "reload" && canResume(run)) continue;
			pi.sendMessage({ customType: RESULTS_TYPE, content: digestLine(run, lostNote(run)), display: true }, { deliverAs: "nextTurn" });
		}
		stopSaving = registry.onChange(save);
	});

	pi.on("session_shutdown", async ({ reason }) => {
		for (const run of registry.live()) if (run.background) registry.update(run.id, { endedBy: reason });
		stopSaving?.();
		stopSaving = undefined;
		const stopped = background.shutdown();
		if (isTeam()) await stopped;
	});

	pi.on("before_agent_start", () => {
		const content = background.digest();
		return content ? { message: { customType: RESULTS_TYPE, content, display: true } } : undefined;
	});

	pi.on("tool_result", (event) => {
		const settings = (pi.getSettings?.() as { llmPrompts?: { forks?: { checkInMinutes?: number } } } | undefined)?.llmPrompts?.forks;
		const minutes = settings?.checkInMinutes ?? DEFAULT_CHECK_IN_MINUTES;
		const note = minutes > 0 ? background.checkIns(minutes * MINUTE_MS) : undefined;
		return note ? { content: [...event.content, { type: "text" as const, text: note }] } : undefined;
	});

	pi.on("agent_end", (event) => background.noteRun(event.messages));

	pi.on("agent_settled", (event, ctx) => {
		background.settle(ctx, event.aborted);
	});

	pi.on("agent_before_settle", async (event, ctx) => {
		if (!ctx.hasUI || isTeam()) await background.hold();
		const content = background.digest();
		if (!content) return undefined;
		return { entries: [...event.entries, { type: "custom_message" as const, customType: RESULTS_TYPE, content, display: true }], continue: true };
	});
}
