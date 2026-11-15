// Shows the live background forks above the editor and a fork's recent steps on request. UI only: nothing reaches the model.
// Commands: /forks [name] (list live and recent forks, or show a fork's last steps)
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";
import { isLive, registryOf, type Registry, type Run } from "./registry.ts";

type Event = { [key: string]: any };
export type Watchable = { watch(listener: (record: Event) => void): () => void };
type Activity = { turns: number; last?: string; usage?: Usage };
type Usage = { context: number; cache: number };
type Paint = { fg(color: string, text: string): string; bold(text: string): string };

const PLAIN: Paint = { fg: (_color, text) => text, bold: (text) => text };
const ROLE_COLORS: Record<string, string> = { reader: "success", writer: "warning" };
const COLD_COLOR = "muted";
const SPINNER = ["◐", "◓", "◑", "◒"];
const LOW_CACHE = 0.5;

const WIDGET_KEY = "pi-context-forks";
const SNIPPET = 60;
const STEP_SNIPPET = 160;
const STEPS = 15;
const RECENT = 10;
const showsUi = (ctx: Pick<ExtensionContext, "hasUI">): boolean => ctx.hasUI && !process.env.PI_CONTEXT_CHILD;
const CLOCK_MS = 1000;

const short = (text: string, max = SNIPPET): string => {
	const flat = text.replace(/\s+/g, " ").trim();
	return flat.length > max ? `${flat.slice(0, max - 3)}...` : flat;
};
const homePath = (file: string): string => {
	const relative = path.relative(process.cwd(), file);
	if (!relative.startsWith("..") && !path.isAbsolute(relative)) return relative || ".";
	const home = os.homedir();
	return file === home || file.startsWith(`${home}/`) ? `~${file.slice(home.length)}` : file;
};
const argOf = (args: Event): string | undefined => {
	if (typeof args.command === "string") return args.command;
	if (typeof args.path === "string") return homePath(args.path);
	const first = Object.values(args).find((value) => typeof value === "string");
	return typeof first === "string" ? first : undefined;
};
const call = (name: string, args: unknown): string => {
	const arg = args && typeof args === "object" ? argOf(args as Event) : undefined;
	return short(arg ? `${name}: ${arg}` : name);
};
const textOf = (message: Event | undefined): string =>
	(Array.isArray(message?.content) ? message.content : []).flatMap((block: Event) => (block.type === "text" ? [block.text] : [])).join(" ");
const tokens = (count: number): string => (count >= 1_000_000 ? `${+(count / 1_000_000).toFixed(1)}M` : count >= 1000 ? `${Math.round(count / 1000)}k` : String(count));
/** A request's context size and the share of its prompt read from cache. */
const usageOf = (usage: Event | undefined): Usage | undefined => {
	const prompt = (usage?.input ?? 0) + (usage?.cacheRead ?? 0) + (usage?.cacheWrite ?? 0);
	return prompt ? { context: prompt + (usage?.output ?? 0), cache: (usage?.cacheRead ?? 0) / prompt } : undefined;
};
const usageText = (usage: Usage | undefined, window: number | undefined, paint: Paint): string => {
	if (!usage) return "";
	const cache = `cache ${Math.round(usage.cache * 100)}%`;
	return paint.fg("dim", ` · ctx ${tokens(usage.context)}${window ? `/${tokens(window)}` : ""} · `) + paint.fg(usage.cache < LOW_CACHE ? "error" : "dim", cache);
};
const elapsed = (ms: number): string => {
	const seconds = Math.max(0, Math.round(ms / 1000));
	return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m${String(seconds % 60).padStart(2, "0")}s`;
};

/** The last steps of a fork, its tool calls and texts, and its last request's usage, read from its session file. */
export function recentSteps(run: Run, limit = STEPS): { steps: string[]; usage?: Usage } {
	const file = run.files && path.join(run.files, "seed.jsonl");
	if (!file || !fs.existsSync(file)) return { steps: [] };
	const steps: string[] = [];
	let usage: Usage | undefined;
	for (const line of fs.readFileSync(file, "utf8").split("\n")) {
		let entry: Event;
		try {
			entry = JSON.parse(line);
		} catch {
			continue;
		}
		if (entry.type !== "message" || entry.message?.role !== "assistant" || Date.parse(entry.timestamp) < run.startedAt) continue;
		usage = usageOf(entry.message.usage) ?? usage;
		for (const block of entry.message.content ?? []) {
			if (block.type === "toolCall") steps.push(`> ${call(block.name, block.arguments)}`);
			else if (block.type === "text" && block.text.trim()) steps.push(`  ${short(block.text, STEP_SNIPPET)}`);
		}
	}
	return { steps: steps.slice(-limit), usage };
}

export class LiveView {
	private activity = new Map<string, Activity>();
	private render: (() => void) | undefined;
	private unbind: (() => void) | undefined;
	private clock: ReturnType<typeof setInterval> | undefined;

	private registry: Registry;
	/** The context window shown against each fork's context size. */
	window: number | undefined;

	constructor(registry: Registry = registryOf()) {
		this.registry = registry;
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

	/** The widget lines, or undefined when no background fork is live. */
	lines(now = Date.now(), paint: Paint = PLAIN, width = Number.POSITIVE_INFINITY): string[] | undefined {
		const live = this.registry.live().filter((run) => run.background);
		if (!live.length) return undefined;
		const frame = SPINNER[Math.floor(now / CLOCK_MS) % SPINNER.length];
		const fit = (line: string) => (Number.isFinite(width) ? truncateToWidth(line, width) : line);
		return [
			fit(paint.fg("dim", "Background forks · /forks <name> for steps")),
			...live.map((run) => {
				const activity = this.activity.get(run.id);
				const turns = activity?.turns ?? 0;
				const role = run.model ? "cold" : run.role;
				const glyph = run.state === "landing" ? paint.fg("success", "↳") : paint.fg("accent", frame);
				const meta = paint.fg("dim", `${elapsed(now - run.startedAt)} · ${turns} turn${turns === 1 ? "" : "s"}`) + usageText(activity?.usage, this.window, paint) + (run.state === "landing" ? paint.fg("dim", " · landing") : "");
				const last = activity?.last ? `  ${paint.fg("muted", activity.last)}` : "";
				return fit(`${glyph} ${paint.fg("accent", paint.bold(run.name))} ${paint.fg(run.model ? COLD_COLOR : (ROLE_COLORS[run.role] ?? COLD_COLOR), `[${role}]`)} ${meta}${last}`);
			}),
		];
	}

	/** Shows the widget in a top-level session with a UI and keeps it current. */
	bind(ctx: ExtensionContext): void {
		if (!showsUi(ctx)) return;
		this.window = ctx.model?.contextWindow;
		this.render = () => {
			const live = Boolean(this.lines());
			ctx.ui.setWidget(WIDGET_KEY, live ? (_tui, theme) => ({ render: (width: number) => this.lines(Date.now(), theme, width) ?? [], invalidate: () => undefined }) : undefined);
			this.tick(live);
		};
		this.unbind?.();
		this.unbind = this.registry.onChange(() => this.render?.());
		this.render();
	}

	/** Stops rendering into a session that has ended. */
	release(): void {
		this.unbind?.();
		this.unbind = undefined;
		this.render = undefined;
		this.tick(false);
	}

	/** Keeps the elapsed times current while a fork is live. */
	private tick(live: boolean): void {
		if (live && !this.clock) {
			this.clock = setInterval(() => this.render?.(), CLOCK_MS);
			this.clock.unref();
		} else if (!live && this.clock) {
			clearInterval(this.clock);
			this.clock = undefined;
		}
	}

	private record(runId: string, record: Event): void {
		const activity = this.activity.get(runId) ?? { turns: 0 };
		if (record.type === "tool_execution_start") activity.last = call(record.toolName, record.args);
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

export function registerLiveView(pi: ExtensionAPI, view: LiveView, registry: Registry = registryOf()) {
	pi.on("session_start", (_event, ctx) => view.bind(ctx));
	pi.on("session_shutdown", () => view.release());

	pi.registerCommand("forks", {
		description: "List live and recent background forks, or show a fork's last steps",
		handler: async (args, ctx) => {
			if (!showsUi(ctx)) return;
			const runs = registry.all().filter((run) => run.background).sort((a, b) => b.startedAt - a.startedAt);
			const name = args.trim();
			if (!name) {
				const now = Date.now();
				ctx.ui.notify(runs.length ? runs.slice(0, RECENT).map((run) => `${run.name} ${run.state} ${elapsed((run.endedAt ?? now) - run.startedAt)}`).join("\n") : "no forks", "info");
				return;
			}
			const run = runs.find((candidate) => candidate.name === name);
			if (!run) {
				ctx.ui.notify(`no fork ${name}. Forks: ${runs.map((candidate) => candidate.name).join(", ") || "none"}`, "warning");
				return;
			}
			const { steps, usage } = recentSteps(run);
			ctx.ui.notify([`${run.name} (${run.role}, ${run.state}${usageText(usage, ctx.model?.contextWindow, PLAIN).replaceAll(" ·", ",")})`, ...(steps.length ? steps : ["no steps kept"])].join("\n"), "info");
		},
	});
}
