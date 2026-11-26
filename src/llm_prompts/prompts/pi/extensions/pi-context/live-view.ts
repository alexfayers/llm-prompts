// Shows the live background forks, and the finished ones until main reads their result and answers their asks, above the editor. UI only: nothing reaches the model.
import path from "node:path";
import os from "node:os";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";
import { cacheLeftMs, cacheText, FINISHED, isLive, registryOf, type Registry, type Run } from "./registry.ts";
import { openAsks } from "../pending-asks.ts";
import { askPrefixes, forkAsking } from "./wake.ts";

type Event = { [key: string]: any };
export type Watchable = { watch(listener: (record: Event) => void): () => void };
type Activity = { turns: number; last?: string; lastCall?: string; watches?: Set<string>; usage?: Usage };
type Usage = { context: number; cache: number };
type Paint = { fg(color: string, text: string): string; bold(text: string): string };

const PLAIN: Paint = { fg: (_color, text) => text, bold: (text) => text };
const ROLE_COLORS: Record<string, string> = { reader: "success", writer: "warning" };
const COLD_COLOR = "muted";
const SPINNER = ["◐", "◓", "◑", "◒"];
const LOW_CACHE = 0.8;
const CALL_CHARS = 40;

const WIDGET_KEY = "pi-context-forks";
const SNIPPET = 60;
const KEY_CHARS = 6;
const WATCH_COMMAND = /\bllm-prompts watch\b/;
const showsUi = (ctx: Pick<ExtensionContext, "hasUI">): boolean => ctx.hasUI && !process.env.PI_CONTEXT_CHILD;
const CLOCK_MS = 1000;

const short = (text: string, max = SNIPPET): string => {
	const flat = text.replace(/\s+/g, " ").trim();
	return flat.length > max ? `${flat.slice(0, max - 3)}...` : flat;
};
const homePath = (file: string): string => {
	const relative = path.relative(process.cwd(), file);
	if (!relative.startsWith("..") && !path.isAbsolute(relative)) return relative || ".";
	return tilde(file);
};
const tilde = (file: string): string => {
	const home = os.homedir();
	return file === home || file.startsWith(`${home}/`) ? `~${file.slice(home.length)}` : file;
};
const targetText = (run: Run): string => (run.target ? ` · ${path.basename(run.target)}` : "");
/** A run's cache group, as ` · from stub`, or ` · from stub#3f9a2c` when other shown runs have a source of that name and another cache key. */
const sourceText = (run: Run, shown: Run[]): string => {
	if (!run.from) return "";
	const ambiguous = shown.some((other) => other.from === run.from && other.cacheKey !== run.cacheKey);
	return ` · from ${run.from}${ambiguous && run.cacheKey ? `#${run.cacheKey.slice(0, KEY_CHARS)}` : ""}`;
};
/** A finished run's cache time left, as ` · cache 3m` or ` · cache expired`. */
const cacheNote = (run: Run, now: number): string => {
	const left = FINISHED.includes(run.state) ? cacheLeftMs(run, now) : undefined;
	return left === undefined ? "" : ` · ${cacheText(left)}`;
};
const argOf = (args: Event): string | undefined => {
	if (typeof args.command === "string") return args.command;
	if (typeof args.path === "string") return homePath(args.path);
	const first = Object.values(args).find((value) => typeof value === "string");
	return typeof first === "string" ? first : undefined;
};
const stripCd = (command: string): string => command.replace(/^cd\s+\S+\s*(?:&&|;)\s*/, "");
const call = (name: string, args: unknown): string => {
	const arg = args && typeof args === "object" ? argOf(args as Event) : undefined;
	const text = arg && name === "bash" ? stripCd(arg) : arg;
	return text ? `${name}: ${short(text, CALL_CHARS)}` : name;
};
const textOf = (message: Event | undefined): string =>
	(Array.isArray(message?.content) ? message.content : []).flatMap((block: Event) => (block.type === "text" ? [block.text] : [])).join(" ");
export const tokens = (count: number): string => (count >= 1_000_000 ? `${+(count / 1_000_000).toFixed(1)}M` : count >= 1000 ? `${Math.round(count / 1000)}k` : String(count));
/** A request's context size and the share of its prompt read from cache. */
const usageOf = (usage: Event | undefined): Usage | undefined => {
	const prompt = (usage?.input ?? 0) + (usage?.cacheRead ?? 0) + (usage?.cacheWrite ?? 0);
	return prompt ? { context: prompt + (usage?.output ?? 0), cache: (usage?.cacheRead ?? 0) / prompt } : undefined;
};
const usageText = (usage: Usage | undefined, window: number | undefined, paint: Paint): string => {
	if (!usage) return "";
	const bigContext = window !== undefined && usage.context > window / 2;
	return (bigContext ? paint.fg("warning", ` · ctx ${tokens(usage.context)}/${tokens(window)}`) : "") + (usage.cache < LOW_CACHE ? paint.fg("error", ` · cache ${Math.round(usage.cache * 100)}%`) : "");
};
/** A cold worker's model, found through its provider/id string. */
export const findModel = (model: string, registry: ExtensionContext["modelRegistry"] | undefined) => {
	const slash = model.indexOf("/");
	if (slash < 0 || !registry) return undefined;
	const provider = model.slice(0, slash);
	const id = model.slice(slash + 1);
	return registry.find(provider, id) ?? (id.includes(":") ? registry.find(provider, id.slice(0, id.lastIndexOf(":"))) : undefined);
};
/** A cold worker's own context window; falls back to main's for a session fork. */
const modelWindow = (model: string, registry: ExtensionContext["modelRegistry"] | undefined): number | undefined => findModel(model, registry)?.contextWindow;
const windowFor = (run: Run, registry: ExtensionContext["modelRegistry"] | undefined, mainWindow: number | undefined): number | undefined => (run.model ? modelWindow(run.model, registry) : mainWindow);
/** A cold worker's model as its tier (`sonnet`, `opus`, `haiku`), or its id without the provider and a Bedrock-style `anthropic.` prefix. */
const shortModel = (model: string): string => {
	const id = model.slice(model.indexOf("/") + 1);
	return id.match(/opus|sonnet|haiku/)?.[0] ?? (id.startsWith("anthropic.") ? id.slice("anthropic.".length) : id);
};
const roleTag = (run: Run, paint: Paint): string => paint.fg(run.model ? COLD_COLOR : (ROLE_COLORS[run.role] ?? COLD_COLOR), `[${run.model ? shortModel(run.model) : run.role}]`);
/** The theme color for a finished run's status glyph. */
const FINISH_COLOR: Record<string, string> = { done: "success", "found-it": "success", blocked: "warning", failed: "error", lost: "error" };
/** The finished runs as one row, such as `✓ 3 done · 1 blocked · cache 2-5m`, each count in its outcome's color. */
const summaryRow = (runs: Run[], now: number, paint: Paint): string => {
	const counts = FINISHED.flatMap((state) => {
		const count = runs.filter((run) => run.state === state).length;
		return count ? [paint.fg(FINISH_COLOR[state], `${count} ${state}`)] : [];
	});
	const minutes = runs.flatMap((run) => {
		const left = cacheLeftMs(run, now);
		return left ? [Math.ceil(left / 60_000)] : [];
	});
	const low = Math.min(...minutes);
	const high = Math.max(...minutes);
	const cache = minutes.length ? ` · cache ${low === high ? low : `${low}-${high}`}m` : runs.some((run) => run.lastRequestAt !== undefined) ? ` · ${cacheText(0)}` : "";
	return `${paint.fg("dim", "✓ ")}${counts.join(paint.fg("dim", " · "))}${paint.fg("dim", cache)}`;
};
const elapsed = (ms: number): string => {
	const seconds = Math.max(0, Math.round(ms / 1000));
	return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m${String(seconds % 60).padStart(2, "0")}s`;
};

export class LiveView {
	private activity = new Map<string, Activity>();
	private render: (() => void) | undefined;
	private unbind: (() => void) | undefined;
	private clock: ReturnType<typeof setInterval> | undefined;

	private registry: Registry;
	private modelRegistry: ExtensionContext["modelRegistry"] | undefined;
	/** The context window shown against each fork's context size, for a run sharing main's model. */
	window: number | undefined;

	/** Whether main has received the run's unread result. */
	private received: (run: Run) => boolean;

	constructor(registry: Registry = registryOf(), received: (run: Run) => boolean = () => false) {
		this.registry = registry;
		this.received = received;
	}

	/** Follows a background fork's child events until the run ends. */
	watch(runId: string, child: Watchable): void {
		const offChild = child.watch((record) => this.record(runId, record));
		const offRun = this.registry.onChange((run) => {
			if (run.id !== runId || isLive(run)) return;
			offChild();
			offRun();
			this.activity.delete(runId);
		});
	}

	/** The turns a live fork's child took, its last tool call, and whether an `llm-prompts watch` call is still running. */
	progress(runId: string): { turns: number; lastCall?: string; watching: boolean } {
		const { turns, lastCall, watches } = this.activity.get(runId) ?? { turns: 0 };
		return { turns, lastCall, watching: Boolean(watches?.size) };
	}

	/** The widget lines, or undefined when no background fork is live or still cached. */
	lines(now = Date.now(), paint: Paint = PLAIN, width = Number.POSITIVE_INFINITY, openIds: string[] = []): string[] | undefined {
		const live = this.registry.live();
		const finished = this.registry.all().filter((run) => FINISHED.includes(run.state));
		const prefixes = askPrefixes(openIds);
		const asking = finished.filter((run) => forkAsking(prefixes, run));
		const unread = finished.filter((run) => run.unread && !this.received(run) && !asking.includes(run));
		if (!live.length && !asking.length && !unread.length) return undefined;
		const shown = [...live, ...asking];
		const frame = SPINNER[Math.floor(now / CLOCK_MS) % SPINNER.length];
		const fit = (line: string) => (Number.isFinite(width) ? truncateToWidth(line, width) : line);
		return [
			fit(paint.fg("dim", "Background forks")),
			...live.map((run) => {
				const activity = this.activity.get(run.id);
				const turns = activity?.turns ?? 0;
				const glyph = run.state === "landing" ? paint.fg("success", "↳") : paint.fg("accent", frame);
				const meta = paint.fg("dim", `${elapsed(now - run.startedAt)} · ${turns} turn${turns === 1 ? "" : "s"}${targetText(run)}${sourceText(run, shown)}`) + usageText(activity?.usage, windowFor(run, this.modelRegistry, this.window), paint) + (run.state === "landing" ? paint.fg("dim", " · landing") : "") + (run.next ? paint.fg("dim", ` · next: ${run.next}`) : "");
				const last = activity?.last ? `  ${paint.fg("muted", activity.last)}` : "";
				return fit(`${glyph} ${paint.fg("accent", paint.bold(run.name))} ${roleTag(run, paint)} ${meta}${last}`);
			}),
			...asking.map((run) => fit(`${paint.fg(FINISH_COLOR[run.state] ?? "dim", "●")} ${paint.fg("accent", run.name)} ${roleTag(run, paint)} ${paint.fg("dim", `${run.state}${cacheNote(run, now)}${sourceText(run, shown)}`)}`)),
			...(unread.length ? [fit(summaryRow(unread, now, paint))] : []),
		];
	}

	/** Shows the widget in a top-level session with a UI and keeps it current. */
	bind(ctx: ExtensionContext): void {
		if (!showsUi(ctx)) return;
		this.window = ctx.model?.contextWindow;
		this.modelRegistry = ctx.modelRegistry;
		let scannedLeaf: string | null | undefined;
		let openIds: string[] = [];
		this.render = () => {
			const leaf = ctx.sessionManager?.getLeafId?.();
			if (leaf === undefined || leaf !== scannedLeaf) {
				scannedLeaf = leaf;
				openIds = openAsks((ctx.sessionManager?.getBranch() ?? []) as Parameters<typeof openAsks>[0]).map((ask) => ask.id);
			}
			const now = Date.now();
			const shown = Boolean(this.lines(now, PLAIN, Number.POSITIVE_INFINITY, openIds));
			ctx.ui.setWidget(
				WIDGET_KEY,
				shown
					? (_tui, theme) => {
							const lines = this.lines(now, theme, Number.POSITIVE_INFINITY, openIds) ?? [];
							return { render: (width: number) => lines.map((line) => truncateToWidth(line, width)), invalidate: () => undefined };
						}
					: undefined,
			);
			this.tick(this.registry.live().length > 0);
		};
		this.unbind?.();
		this.unbind = this.registry.onChange(() => this.render?.());
		this.render();
	}

	/** Renders the widget again, such as once main has received results. */
	refresh(): void {
		this.render?.();
	}

	/** Stops rendering into a session that has ended. */
	release(): void {
		this.unbind?.();
		this.unbind = undefined;
		this.render = undefined;
		this.tick(false);
	}

	/** Keeps the elapsed times current while a background fork is live. */
	private tick(live: boolean): void {
		if (live && !this.clock) {
			this.clock = setInterval(() => this.render?.(), CLOCK_MS);
			this.clock.unref();
		} else if (!live && this.clock) {
			clearInterval(this.clock);
			this.clock = undefined;
		}
	}

	/** Shows `text` as a fork's activity until its next step, or clears it. */
	note(runId: string, text: string | undefined): void {
		this.activity.set(runId, { ...(this.activity.get(runId) ?? { turns: 0 }), last: text });
		this.render?.();
	}

	private record(runId: string, record: Event): void {
		const activity = this.activity.get(runId) ?? { turns: 0 };
		if (record.type === "tool_execution_start") {
			activity.last = activity.lastCall = call(record.toolName, record.args);
			if (WATCH_COMMAND.test(record.args?.command ?? "")) (activity.watches ??= new Set()).add(record.toolCallId);
		} else if (record.type === "tool_execution_end") activity.watches?.delete(record.toolCallId);
		else if (record.type === "message_end" && record.message?.role === "assistant") {
			activity.turns++;
			activity.usage = usageOf(record.message.usage) ?? activity.usage;
			const text = textOf(record.message);
			if (text.trim()) activity.last = short(text);
		} else return;
		this.activity.set(runId, activity);
		this.render?.();
	}
}

export function registerLiveView(pi: ExtensionAPI, view: LiveView) {
	pi.on("session_start", (_event, ctx) => view.bind(ctx));
	pi.on("turn_end", () => view.refresh());
	pi.on("session_shutdown", () => view.release());
}
