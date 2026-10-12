// Draws the permission prompt and its preview as a centred box.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { matchesKey, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

const PATCH = Symbol.for("llm-prompts.permission-box");
const BOXED = Symbol.for("llm-prompts.permission-box.boxed");
const PROMPT_CLASS = "PermissionPromptComponent";
const PROMPT_TITLE = /^Permission Required/;
const PROBE_WIDTH = 80;
const BORDER_LEFT = "\u2502 ";
const BORDER_RIGHT = " \u2502";
const BORDER_OVERHEAD = BORDER_LEFT.length + BORDER_RIGHT.length;
const CORNER_ROWS = 2;
const TITLE_MARGIN = 4;
const PREVIEW_SLOT = Symbol.for("llm-prompts.permission-preview");
const MAX_HEIGHT_PERCENT = 85;
const OVERLAY_MARGIN = 1;
const MIN_OVERLAY_ROWS = 8;
const MIN_PREVIEW_ROWS = 3;
const SECTION_CHROME_ROWS = 3;
const SCROLL_HINT = "Wheel  Alt+Up/Alt+Down";
const OVERLAY_OPTIONS = {
	anchor: "center",
	width: "92%",
	minWidth: 40,
	maxHeight: `${MAX_HEIGHT_PERCENT}%`,
	margin: OVERLAY_MARGIN,
} as const;
const KEY_SCROLL: [string, number][] = [
	["alt+up", -1],
	["alt+down", 1],
];
const SELECTED_MARKER = "\u25b6";
const ARROW_MARKER = "\u2192";
const HINT_SEPARATOR = " \u00b7 ";
const HINT_BULLET = " \u2022 ";
const TEXT_INDENT = " ";
const OPTION_ROW = /^(?:[\u25b6\u2192]| ) \(/;
const ANSI = /\x1b\[[\d;]*m/g;
const OPTIONAL_MEMBERS = ["dispose", "wantsKeyRelease"] as const;

type Theme = { fg(color: string, text: string): string; bold(text: string): string };
type Inner = {
	render(width: number): string[];
	handleInput?(data: string): void;
	invalidate?(): void;
	focused?: boolean;
	handleMouse?(event: WheelEvent): unknown;
	[BOXED]?: true;
};
type Tui = { terminal: { rows: number }; requestRender(): void };
type Preview = { title: string; lines(width: number, theme: Theme): string[] };
type WheelEvent = { type: string; wheelDelta?: number };
type Factory = (tui: Tui, theme: Theme, keybindings: unknown, done: (result: unknown) => void) => Inner | Promise<Inner>;
type CustomOptions = { overlay?: boolean; overlayOptions?: object };
type Custom = (factory: Factory, options?: CustomOptions) => Promise<unknown>;
type CustomUi = { custom: Custom; [PATCH]?: Custom };

const plain = (text: string): string => text.replace(ANSI, "");

function isPermissionPrompt(component: Inner): boolean {
	return component.constructor?.name === PROMPT_CLASS || PROMPT_TITLE.test(plain(component.render(PROBE_WIDTH)[0] ?? ""));
}

function restyleRow(theme: Theme, line: string): string {
	const text = plain(line);
	if (!OPTION_ROW.test(text)) return TEXT_INDENT + line;
	return text.startsWith(SELECTED_MARKER) || text.startsWith(ARROW_MARKER) ? theme.bold(line.replace(SELECTED_MARKER, ARROW_MARKER)) : line;
}

function restyleHints(theme: Theme, line: string): string {
	const text = plain(line);
	if (!text.includes(HINT_SEPARATOR)) return line;
	const hints = text.split(HINT_SEPARATOR).map((hint) => {
		const [key = "", ...description] = hint.split(" ");
		return theme.fg("dim", key) + (description.length ? theme.fg("muted", ` ${description.join(" ")}`) : "");
	});
	return TEXT_INDENT + theme.fg("dim", hints.join(HINT_BULLET));
}

function failOpen(restyle: (line: string) => string, line: string): string {
	try {
		return restyle(line);
	} catch {
		return line;
	}
}

function frame(theme: Theme, lines: string[], width: number): string[] {
	const accent = (text: string): string => theme.fg("accent", text);
	const inner = Math.max(0, width - CORNER_ROWS);
	const [first = "", ...rest] = lines;
	const title = plain(first).trim();
	const body = title ? rest : lines;
	const label = ` ${title} `;
	const top =
		!title || inner < label.length + TITLE_MARGIN
			? accent(`\u256d${"\u2500".repeat(inner)}\u256e`)
			: accent("\u256d\u2500") + theme.fg("dim", theme.bold(label)) + accent("\u2500".repeat(inner - 1 - label.length) + "\u256e");
	const side = Math.max(1, width - BORDER_OVERHEAD);
	return [
		top,
		...body.map((line) => accent(BORDER_LEFT) + truncateToWidth(line, side, "", true) + accent(BORDER_RIGHT)),
		accent(`\u2570${"\u2500".repeat(inner)}\u256f`),
	];
}

class BoxedPrompt {
	[BOXED] = true as const;

	private top = 0;
	private shown = { rows: 0, total: 0 };
	private readonly prompt: Inner;
	private readonly theme: Theme;
	private readonly tui: Tui;
	private readonly requestId: string | undefined;

	constructor(prompt: Inner, theme: Theme, tui: Tui, requestId: string | undefined) {
		this.prompt = prompt;
		this.theme = theme;
		this.tui = tui;
		this.requestId = requestId;
		const forward = this as unknown as Record<string, unknown>;
		const target = prompt as unknown as Record<string, ((...args: unknown[]) => unknown) | undefined>;
		for (const member of OPTIONAL_MEMBERS) {
			if (typeof target[member] === "function") forward[member] = (...args: unknown[]) => target[member]?.(...args);
		}
		if ("focused" in prompt) {
			Object.defineProperty(this, "focused", { get: () => prompt.focused, set: (value: boolean) => void (prompt.focused = value) });
		}
	}

	private maxRows(): number {
		const available = Math.max(1, this.tui.terminal.rows - 2 * OVERLAY_MARGIN);
		const ratio = Math.max(1, Math.floor((this.tui.terminal.rows * MAX_HEIGHT_PERCENT) / 100));
		return Math.min(available, Math.max(Math.min(MIN_OVERLAY_ROWS, available), ratio));
	}

	private previewSection(width: number, dialogRows: number): string[] {
		this.shown = { rows: 0, total: 0 };
		const preview = this.requestId === undefined ? undefined : ((globalThis as Record<symbol, unknown>)[PREVIEW_SLOT] as Map<string, Preview> | undefined)?.get(this.requestId);
		if (!preview) return [];
		try {
			const all = preview.lines(Math.max(1, width - BORDER_OVERHEAD), this.theme);
			const room = this.maxRows() - CORNER_ROWS - dialogRows - SECTION_CHROME_ROWS;
			if (all.length === 0 || room < MIN_PREVIEW_ROWS) return [];
			const rows = Math.min(all.length, room);
			this.top = Math.min(this.top, all.length - rows);
			this.shown = { rows, total: all.length };
			const range = `${this.top + 1}-${this.top + rows}/${all.length}`;
			return [
				TEXT_INDENT + this.theme.bold(preview.title),
				...all.slice(this.top, this.top + rows),
				TEXT_INDENT + this.theme.fg("dim", `${SCROLL_HINT}  ${range}`),
				this.theme.fg("dim", "\u2500".repeat(Math.max(0, width - BORDER_OVERHEAD))),
			];
		} catch {
			return [];
		}
	}

	private scrollBy(lines: number): boolean {
		if (this.shown.rows === 0) return false;
		this.top = Math.min(Math.max(0, this.top + lines), this.shown.total - this.shown.rows);
		this.tui.requestRender();
		return true;
	}

	render(width: number): string[] {
		const lines = this.prompt.render(Math.max(1, width - BORDER_OVERHEAD - TEXT_INDENT.length));
		try {
			const styled = lines.map((line, index) =>
				failOpen((text) => (index === lines.length - 1 ? restyleHints(this.theme, text) : restyleRow(this.theme, text)), line),
			);
			const [title = "", ...dialog] = styled;
			return frame(this.theme, [title, ...this.previewSection(width, dialog.length), ...dialog], width);
		} catch {
			return this.prompt.render(width);
		}
	}

	handleInput(data: string): void {
		const lines = KEY_SCROLL.find(([key]) => matchesKey(data, key as never))?.[1];
		if (lines !== undefined && this.scrollBy(lines)) return;
		this.prompt.handleInput?.(data);
	}

	handleMouse(event: WheelEvent): unknown {
		if (event.type === "wheel" && this.scrollBy(event.wheelDelta ?? 0)) return { handled: true };
		return this.prompt.handleMouse?.(event);
	}

	invalidate(): void {
		this.prompt.invalidate?.();
	}
}

function boxed(component: Inner, theme: Theme, tui: Tui, requestId: string | undefined): Inner {
	try {
		return component[BOXED] || !isPermissionPrompt(component) ? component : (new BoxedPrompt(component, theme, tui, requestId) as unknown as Inner);
	} catch {
		return component;
	}
}

export default function (pi: ExtensionAPI): void {
	let announced: string | undefined;
	pi.events.on("permissions:ui_prompt", (data) => {
		announced = (data as { requestId: string }).requestId;
	});
	pi.events.on("permissions:decision", (data) => {
		if ((data as { requestId: string }).requestId === announced) announced = undefined;
	});
	pi.on("session_start", (_event, ctx) => {
		announced = undefined;
		if (ctx.mode !== "tui") return;
		const ui = ctx.ui as unknown as CustomUi;
		if (ui.custom === ui[PATCH]) return;
		const original = ui.custom.bind(ui);
		const patched: Custom = (factory, options) => {
			if (options?.overlay) return original(factory, options);
			const requestId = announced;
			const shownOptions: CustomOptions | undefined = requestId === undefined ? options : { overlay: true, overlayOptions: OVERLAY_OPTIONS };
			announced = undefined;
			return original((tui, theme, keybindings, done) => {
				const made = factory(tui, theme, keybindings, done);
				return made instanceof Promise ? made.then((component) => boxed(component, theme, tui, requestId)) : boxed(made, theme, tui, requestId);
			}, shownOptions);
		};
		ui.custom = patched;
		ui[PATCH] = patched;
	});
}
