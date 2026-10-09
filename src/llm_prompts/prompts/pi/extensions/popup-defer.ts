import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const DEFAULT_DEBOUNCE_MS = 1500;
const DEFAULT_MAX_HOLD_MS = 30_000;
const DEFAULT_SWALLOW_MS = 400;
const USAGE = "Usage: /popup-defer [on|off|<ms>]";
const PATCH = Symbol.for("llm-prompts.popup-defer");
const OPTIONS_ARG = 2;
const DIALOG_METHODS = {
	custom: undefined,
	select: OPTIONS_ARG,
	confirm: OPTIONS_ARG,
	input: OPTIONS_ARG,
	editor: undefined,
};

const DIALOG_NAMES = Object.keys(DIALOG_METHODS) as Array<keyof typeof DIALOG_METHODS>;

type DialogMethod = (...args: unknown[]) => Promise<unknown>;
type DialogUi = Record<keyof typeof DIALOG_METHODS, DialogMethod>;
type Patch = { originals: DialogUi; unsubscribe: () => void };
type DialogOptions = { signal?: AbortSignal; timeout?: number };
type Hold = { deadline: number; expiry: number; settle: (proceed: boolean) => void };

const NON_KEYBOARD_INPUT = [
	/^\x1b\[<[\d;]*[Mm]$/, // SGR mouse
	/^\x1b\[M[\s\S]{3}$/, // legacy mouse
	/^\x1b\[[IO]$/, // focus in/out
	/^\x1b\[\?[\d;]*n$/, // colour scheme report
	/^\x1b\[[\d;]*(?::\d+)*;\d+:3[\d;:]*[u~A-Z]$/, // key release
];

const PRINTABLE = /^[^\x00-\x1f\x7f]+$/;
const ENTER = /^(?:\r|\n|\x1b\[13(?:;\d+)?u)$/;

function isKeystroke(data: string): boolean {
	return !NON_KEYBOARD_INPUT.some((pattern) => pattern.test(data));
}

function readDebounceMs(value: string | undefined): number {
	const parsed = Number(value);
	return value === undefined || value.trim() === "" || !Number.isFinite(parsed) || parsed < 0 ? DEFAULT_DEBOUNCE_MS : parsed;
}

function positiveTimeout(options: DialogOptions | undefined): number | undefined {
	return options?.timeout !== undefined && options.timeout > 0 ? options.timeout : undefined;
}

export default function (pi: ExtensionAPI) {
	register(pi);
}

export type Limits = { maxHoldMs: number; swallowMs: number };

export function register(pi: ExtensionAPI, limits: Partial<Limits> = {}) {
	const maxHoldMs = limits.maxHoldMs ?? DEFAULT_MAX_HOLD_MS;
	const swallowMs = limits.swallowMs ?? DEFAULT_SWALLOW_MS;
	let lastKey: number | undefined;
	let swallowUntil = 0;
	let debounceMs = DEFAULT_DEBOUNCE_MS;
	let onMs = DEFAULT_DEBOUNCE_MS;
	let timer: ReturnType<typeof setTimeout> | undefined;
	const queue: Hold[] = [];

	function quietWait(now: number): number {
		return lastKey === undefined ? 0 : lastKey + debounceMs - now;
	}

	function pump(): void {
		clearTimeout(timer);
		const now = Date.now();
		for (const entry of queue.filter((held) => held.expiry <= now)) release(entry, false);
		while (queue[0] && (quietWait(now) <= 0 || queue[0].deadline <= now)) release(queue[0], true);
		if (queue.length === 0) return;
		const wake = Math.min(now + quietWait(now), queue[0].deadline, ...queue.map((entry) => entry.expiry));
		timer = setTimeout(pump, wake - now);
		timer.unref();
	}

	function release(entry: Hold, proceed: boolean): void {
		queue.splice(queue.indexOf(entry), 1);
		entry.settle(proceed);
	}

	function hold(options: DialogOptions | undefined): Promise<boolean> {
		return new Promise((settle) => {
			if (options?.signal?.aborted) return settle(false);
			const now = Date.now();
			const entry: Hold = { deadline: now + maxHoldMs, expiry: now + (positiveTimeout(options) ?? Infinity), settle };
			queue.push(entry);
			options?.signal?.addEventListener(
				"abort",
				() => {
					if (queue.includes(entry)) release(entry, false);
					pump();
				},
				{ once: true },
			);
			pump();
		});
	}

	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		debounceMs = readDebounceMs(process.env.PI_POPUP_DEFER_MS);
		onMs = debounceMs > 0 ? debounceMs : DEFAULT_DEBOUNCE_MS;
		const ui = ctx.ui as unknown as DialogUi & { [PATCH]?: Patch };
		ui[PATCH]?.unsubscribe();
		const originals = ui[PATCH]?.originals ?? (Object.fromEntries(DIALOG_NAMES.map((method) => [method, ui[method]])) as DialogUi);
		const unsubscribe = ctx.ui.onTerminalInput((data) => {
			if (ENTER.test(data)) lastKey = undefined;
			else if (isKeystroke(data)) lastKey = Date.now();
			pump();
			return Date.now() < swallowUntil && PRINTABLE.test(data) ? { consume: true } : undefined;
		});
		ui[PATCH] = { originals, unsubscribe };
		for (const method of DIALOG_NAMES) {
			const optionsArg = DIALOG_METHODS[method];
			const original = originals[method].bind(ui);
			ui[method] = async (...args) => {
				if (debounceMs === 0) return original(...args);
				const options = optionsArg === undefined ? undefined : (args[optionsArg] as DialogOptions | undefined);
				const requested = Date.now();
				if (!(await hold(options))) return undefined;
				const timeout = positiveTimeout(options);
				if (timeout !== undefined) args[optionsArg as number] = { ...options, timeout: timeout - (Date.now() - requested) };
				const shown = original(...args);
				swallowUntil = Date.now() + swallowMs;
				return shown;
			};
		}
	});
	pi.registerCommand("popup-defer", {
		description: "Hold dialogs while you type. `on|off|<ms>` sets the quiet time for this session.",
		handler: async (args, ctx) => {
			const word = args.trim();
			const value = word === "on" ? onMs : word === "off" ? 0 : word === "" ? NaN : Number(word);
			if (word !== "" && Number.isInteger(value) && value >= 0) {
				debounceMs = value;
				if (value > 0) onMs = value;
				pump();
			} else if (word !== "") {
				ctx.ui.notify(USAGE, "warning");
				return;
			}
			ctx.ui.notify(debounceMs > 0 ? `popup-defer on, ${debounceMs} ms` : "popup-defer off", "info");
		},
	});
}
