import assert from "node:assert/strict";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, afterEach, describe, mock, test } from "node:test";
import { useEnv } from "./helpers.ts";

const ESC = /\x1b\[[\d;]*m/g;
const plain = (lines: string[]) => lines.map((line) => line.replace(ESC, ""));
const widths = (lines: string[]) => lines.map((line) => line.replace(ESC, "").length);
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const settle = () => new Promise((resolve) => setImmediate(resolve));
const PREVIEW_SLOT = Symbol.for("llm-prompts.permission-preview");
const SERVICES_KEY = Symbol.for("@gotgenes/pi-permission-system:session-services");
const OVERLAY = { overlay: true, overlayOptions: { anchor: "center", width: "92%", minWidth: 40, maxHeight: "85%", margin: 1 } };
const EXTENSIONS_DIR = join(import.meta.dirname, "../../src/llm_prompts/prompts/pi/extensions");

mock.module("@earendil-works/pi-tui", {
	namedExports: {
		visibleWidth: (text: string) => text.replace(ESC, "").length,
		truncateToWidth: (text: string, width: number, _ellipsis = "", pad = false) => {
			const stripped = text.replace(ESC, "");
			return stripped.length > width ? stripped.slice(0, width) : pad ? text + " ".repeat(width - stripped.length) : text;
		},
		matchesKey: (data: string, key: string) => data === key,
		wrapTextWithAnsi: (text: string, width: number) =>
			text.length === 0 ? [""] : Array.from({ length: Math.ceil(text.length / width) }, (_, n) => text.slice(n * width, (n + 1) * width)),
	},
});
mock.module("@earendil-works/pi-coding-agent", {
	namedExports: { getAgentDir: () => "/nonexistent-agent-dir", generateDiffString: () => ({ diff: "" }), renderDiff: (text: string) => text },
});

const theme = {
	fg: (color: string, text: string) => `\x1b[3${({ accent: 1, dim: 2, muted: 3 } as Record<string, number>)[color] ?? 2}m${text}\x1b[0m`,
	bold: (text: string) => `\x1b[1m${text}\x1b[0m`,
};
const dim = (text: string) => theme.fg("dim", text);
const muted = (text: string) => theme.fg("muted", text);

class PermissionPromptComponent {
	calls: unknown[][] = [];
	seen: number[] = [];
	[key: string]: any;
	lines: string[];
	constructor(lines = ["Permission Required", "body", "", "> (y) Yes"]) {
		this.lines = lines;
	}
	render(width: number) {
		this.seen.push(width);
		return this.lines.map((line, index) => (index === 0 ? theme.fg("accent", line) : line));
	}
	handleInput(data: string) {
		this.calls.push(["input", data]);
	}
	invalidate() {
		this.calls.push(["invalidate"]);
	}
}

let loads = 0;
let previews: Map<string, unknown>;

/** Loads the named extensions against one shared event bus, then starts a tui session. */
async function setup(names = ["permission-box"], cwd = "/") {
	const handlers: Record<string, ((...args: any[]) => unknown)[]> = {};
	const on = (name: string, handler: (...args: any[]) => unknown) => void (handlers[name] ??= []).push(handler);
	const pi: any = { events: { on }, on, registerCommand() {} };
	const emit = async (name: string, payload: unknown, ctx?: unknown) => {
		for (const handler of handlers[name] ?? []) await handler(payload, ctx);
	};
	const shown: any[] = [];
	const log: string[] = [];
	const listeners = new Set<(data: string) => unknown>();
	const ui: any = {
		notify() {},
		select: async () => undefined,
		confirm: async () => undefined,
		input: async () => undefined,
		editor: async () => undefined,
		onTerminalInput: (listener: (data: string) => unknown) => (listeners.add(listener), () => listeners.delete(listener)),
		custom(factory: any, options: any) {
			const entry: any = { options };
			shown.push(entry);
			return new Promise((resolve) => {
				const tui = { terminal: { rows: 40, columns: 100 }, getFocusedComponent: () => entry.component, requestRender() {} };
				const made = factory(tui, theme, undefined, () => (log.push(`closed ${options?.overlay ? "overlay" : "dialog"}`), resolve(undefined)));
				log.push(`shown ${options?.overlay ? "overlay" : "dialog"}`);
				if (made instanceof Promise) made.then((component) => (entry.component = component));
				else entry.component = made;
			});
		},
	};
	previews = (globalThis as Record<symbol, any>)[PREVIEW_SLOT] = new Map();
	const modules = [];
	for (const name of names) modules.push(await import(`${pathToFileURL(join(EXTENSIONS_DIR, `${name}.ts`))}?load=${loads++}`));
	for (const module of modules) module.default(pi);
	const ctx = { mode: "tui", cwd, ui };
	await emit("session_start", {}, ctx);
	/** Opens a dialog and returns what the host holds for it. */
	const open = async (component: any = new PermissionPromptComponent(), options: any = { overlay: false }) => {
		void ui.custom(() => component, options);
		await settle();
		return shown.at(-1).component;
	};
	const rows = (lines: string[]) => open(new PermissionPromptComponent(["Permission Required", ...lines]));
	return { emit, ui, ctx, shown, log, open, rows, type: (data: string) => listeners.forEach((listener) => listener(data)) };
}

after(() => mock.restoreAll());
afterEach(() => delete (globalThis as Record<symbol, unknown>)[PREVIEW_SLOT]);

describe("box", () => {
	test("frames the prompt in a rounded accent box titled from its first line", async () => {
		const { open } = await setup();
		const inner = new PermissionPromptComponent();
		const box = await open(inner);
		const lines = box.render(30);
		assert.deepEqual(plain(lines), [
			"╭─ Permission Required ──────╮",
			"│  body                      │",
			"│                            │",
			"│ > (y) Yes                  │",
			"╰────────────────────────────╯",
		]);
		assert.ok(lines[0].startsWith("\x1b[31m╭─\x1b[0m\x1b[32m\x1b[1m"));
		const wide = box.render(100);
		assert.deepEqual(widths(wide), Array(5).fill(100));
		assert.deepEqual(plain(wide).map((line) => line[0]), ["╭", "│", "│", "│", "╰"]);
		assert.deepEqual(widths(lines), Array(5).fill(30));
		assert.deepEqual(inner.seen, [25, 95]);
	});

	test("turns the selected option marker into a bold arrow", async () => {
		const { rows } = await setup();
		const [, selected, other] = (await rows(["body", theme.fg("accent", "▶ (y) Yes"), "  (n) No"])).render(40).slice(1, -1);
		assert.equal(selected, "\x1b[31m│ \x1b[0m\x1b[1m\x1b[31m→ (y) Yes\x1b[0m\x1b[0m" + " ".repeat(27) + "\x1b[31m │\x1b[0m");
		assert.ok(!other.includes("→") && !other.includes("\x1b[1m"));
	});

	test("indents text rows one column further than option rows", async () => {
		const { rows } = await setup();
		const lines = plain((await rows(["tool  : edit", "", "▶ (y) Yes", "  (n) No", "a · b"])).render(40)).slice(1, -1);
		assert.deepEqual(
			lines.map((line) => line.replace(/[ │]+$/, "")),
			["│  tool  : edit", "", "│ → (y) Yes", "│   (n) No", "│  a • b"],
		);
	});

	test("restyles the key hints line with dim keys, muted descriptions and plain bullets", async () => {
		const { rows } = await setup();
		const lines = (await rows(["a · b", "", muted("↑/↓ move · enter confirm · esc")])).render(60);
		const styled = dim(dim("↑/↓") + muted(" move") + " • " + dim("enter") + muted(" confirm") + " • " + dim("esc"));
		assert.ok(lines[3].split("│ \x1b[0m")[1].startsWith(" " + styled));
		assert.ok(plain(lines)[3].replace(/[ │]+$/, "").endsWith("↑/↓ move • enter confirm • esc"));
		assert.ok(!lines[1].includes("•") && lines[1].includes("·"));
	});

	test("keeps the original row when restyling it fails", async () => {
		const { rows } = await setup();
		const box = await rows(["▶ (y) Yes", "a · b"]);
		box.theme = { fg: (_color: string, text: string) => text, bold: (text: string) => { if (text.includes("→")) throw new Error("boom"); return text; } };
		const lines = plain(box.render(40));
		assert.ok(lines[1].startsWith("│ ▶ (y) Yes"));
		assert.ok(lines.length === 4 && lines[0].startsWith("╭") && lines[3].startsWith("╰"));
	});

	test("shows the prompt unframed when framing fails", async () => {
		const { open } = await setup();
		const box = await open();
		box.theme = { fg: () => { throw new Error("boom"); }, bold: (text: string) => text };
		assert.deepEqual(plain(box.render(30)), ["Permission Required", "body", "", "> (y) Yes"]);
	});
});

describe("overlay", () => {
	test("overlays only the first dialog after the announcement, and a decision withdraws it", async () => {
		const { emit, open, shown } = await setup();
		await emit("permissions:ui_prompt", { requestId: "r1" });
		await open();
		await open();
		await emit("permissions:ui_prompt", { requestId: "r2" });
		await emit("permissions:decision", { requestId: "r2" });
		await open();
		await emit("permissions:ui_prompt", { requestId: "r3" });
		await emit("permissions:decision", { requestId: "r-other" });
		await open(undefined, undefined);
		assert.deepEqual(shown.map((entry) => entry.options), [OVERLAY, { overlay: false }, { overlay: false }, OVERLAY]);
	});

	test("forgets an announced prompt on a new session", async () => {
		const { emit, open, ctx, shown } = await setup();
		await emit("permissions:ui_prompt", { requestId: "r1" });
		await emit("session_start", {}, ctx);
		await open();
		assert.deepEqual(shown[0].options, { overlay: false });
	});
});

describe("preview", () => {
	const announce = async (setupResult: Awaited<ReturnType<typeof setup>>, preview: unknown, prompt?: PermissionPromptComponent) => {
		previews.set("r1", preview);
		await setupResult.emit("permissions:ui_prompt", { requestId: "r1" });
		return setupResult.open(prompt);
	};
	const long = { title: "Diff", lines: () => Array.from({ length: 100 }, (_, n) => `+line ${n}`) };
	const range = (box: any) => plain(box.render(60)).find((line) => line.includes("Wheel"))!.replace(/[│ ]+$/, "").split("  ").pop();

	test("shows a published preview inside the box above a divider and the dialog", async () => {
		const box = await announce(await setup(), { title: "Diff for f.md (+2 -0)", lines: (width: number) => ["+one", "+two"].map((line) => line.padEnd(width, " ")) });
		const lines = box.render(40);
		assert.deepEqual(
			plain(lines).map((line) => line.replace(/[ │─╮╯]+$/, "")),
			["╭─ Permission Required", "│  Diff for f.md (+2 -0)", "│ +one", "│ +two", "│  Wheel  Alt+Up/Alt+Down  1-2/2", "", "│  body", "", "│ > (y) Yes", "╰"],
		);
		assert.equal(plain(lines)[5], "│ " + "─".repeat(36) + " │");
		assert.deepEqual(new Set(widths(lines)), new Set([40]));
		assert.ok(lines[1].includes("\x1b[1m"));
		assert.equal(lines[5].split("\x1b[32m").length - 1, 1);
	});

	for (const [label, preview] of [
		["has none for its request", undefined],
		["throws", { title: "Diff", lines: () => { throw new Error("boom"); } }],
	] as const) {
		test(`holds only the dialog when the preview ${label}`, async () => {
			const s = await setup();
			previews.set("other", { title: "x", lines: () => ["+one"] });
			const box = await announce(s, preview);
			assert.equal(box.render(40).length, 5);
		});
	}

	test("gives the preview what remains of the overlay height after the dialog", async () => {
		const box = await announce(await setup(), long);
		assert.deepEqual([box.render(60).length, range(box)], [34, "1-26/100"]);
	});

	test("shows only the dialog on a terminal too short for three preview rows", async () => {
		const box = await announce(await setup(), long);
		box.tui.terminal.rows = 12;
		const short = box.render(60).length;
		box.tui.terminal.rows = 13;
		assert.deepEqual([short, box.render(60).length], [5, 11]);
	});

	test("scrolls on wheel and alt arrows within bounds and requests a render", async () => {
		const s = await setup();
		const inner = new PermissionPromptComponent();
		const box = await announce(s, long, inner);
		let renders = 0;
		box.tui.requestRender = () => renders++;
		box.render(60);
		const wheel = (delta: number) => box.handleMouse({ type: "wheel", wheelDelta: delta });
		const seen = [wheel(3), range(box)];
		box.handleInput("alt+down");
		seen.push(range(box));
		box.handleInput("alt+up");
		box.handleInput("alt+up");
		seen.push(range(box));
		wheel(1000);
		seen.push(range(box));
		wheel(-1000);
		seen.push(range(box));
		assert.deepEqual(seen, [{ handled: true }, "4-29/100", "5-30/100", "3-28/100", "75-100/100", "1-26/100"]);
		assert.equal(renders, 6);
		assert.deepEqual(inner.calls, []);
	});

	test("passes other keys, and wheels without a preview, to the prompt", async () => {
		const { open } = await setup();
		const inner = new PermissionPromptComponent();
		const mouse: unknown[] = [];
		inner.handleMouse = (event: unknown) => (mouse.push(event), { handled: true });
		const box = await open(inner);
		box.render(60);
		box.handleInput("alt+down");
		box.handleInput("y");
		assert.deepEqual(inner.calls, [["input", "alt+down"], ["input", "y"]]);
		assert.deepEqual(box.handleMouse({ type: "wheel", wheelDelta: 2 }), { handled: true });
		assert.deepEqual(mouse, [{ type: "wheel", wheelDelta: 2 }]);
	});
});

describe("wrapping", () => {
	test("passes other components and overlays through untouched", async () => {
		const { open, shown } = await setup();
		const other = { render: () => ["x"] };
		const overlaid = new PermissionPromptComponent();
		await open(other);
		await open(overlaid, { overlay: true });
		assert.deepEqual([shown[0].component === other, shown[1].component === overlaid], [true, true]);
	});

	test("recognises a prompt by its title line when the class name differs", async () => {
		const { ui, shown } = await setup();
		const make = () => ({ render: () => ["Permission Required (Subagent)", "b"], handleInput() {}, invalidate() {} });
		void ui.custom(make, { overlay: false });
		void ui.custom(async () => make(), { overlay: false });
		await settle();
		assert.equal(shown.length, 2);
		for (const { component } of shown) assert.ok(plain(component.render(50))[0].trimStart().startsWith("╭─ Permission Required (Sub"));
	});

	test("forwards input, invalidate, focus, mouse and dispose to the prompt", async () => {
		const { open } = await setup();
		const inner = new PermissionPromptComponent();
		inner.focused = false;
		const events: unknown[][] = [];
		inner.handleMouse = (event: unknown) => (events.push(["mouse", event]), { handled: true });
		inner.dispose = () => events.push(["dispose"]);
		const box = await open(inner);
		box.handleInput("y");
		box.invalidate();
		box.focused = true;
		assert.deepEqual(box.handleMouse({ type: "wheel" }), { handled: true });
		box.dispose();
		box.render(44);
		assert.deepEqual(inner.calls, [["input", "y"], ["invalidate"]]);
		assert.deepEqual(events, [["mouse", { type: "wheel" }], ["dispose"]]);
		assert.deepEqual([inner.focused, box.focused, inner.seen], [true, true, [39]]);
		const bare = await open(new PermissionPromptComponent());
		assert.deepEqual(["handleMouse", "dispose", "focused"].map((key) => key in bare), [true, false, false]);
	});
});

describe("with popup-defer and diff-preview", () => {
	useEnv({ PI_POPUP_DEFER_MS: "100" });

	async function start(order: string[], restart = false) {
		const authorizers = new Map<string, (details: unknown) => Promise<unknown>>();
		const service = { registerAuthorizer: (name: string, fn: any) => (authorizers.set(name, fn), () => {}), registerToolInputFormatter: () => () => {} };
		(globalThis as Record<symbol, unknown>)[SERVICES_KEY] = new Map([["sess", service]]);
		const s = await setup(order);
		if (restart) await s.emit("session_start", {}, s.ctx);
		await s.emit("permissions:ready", { sessionId: "sess" });
		const ask = async (requestId: string) => {
			const request = { toolName: "edit", value: "f.md", requester: { agentName: null, forwarded: false } };
			const evidence = [{ label: "input", text: "for 'f.md' (+1 -0)\n+body" }];
			await authorizers.get("diff-preview")!({ requestId, payload: { request, evidence } });
			await s.emit("permissions:ui_prompt", { requestId });
			void s.ui.custom(() => new PermissionPromptComponent(), { overlay: false });
		};
		return { ...s, ask, overlays: () => s.shown.filter((entry) => entry.options?.overlay) };
	}

	const ORDERS = [
		["popup-defer", "permission-box", "diff-preview"],
		["permission-box", "popup-defer", "diff-preview"],
		["diff-preview", "permission-box", "popup-defer"],
		["diff-preview", "popup-defer", "permission-box"],
	];
	for (const order of ORDERS)
		for (const typingAndRestart of [false, true]) {
			test(`opens the prompt once as one overlay holding the diff (${order.map((name) => name.slice(0, 3))}, typing and restart ${typingAndRestart})`, async () => {
				const s = await start(order, typingAndRestart);
				if (typingAndRestart) s.type("x");
				await s.ask("r1");
				await sleep(30);
				assert.deepEqual([...s.log], typingAndRestart ? [] : ["shown overlay"]);
				await sleep(250);
				assert.deepEqual(s.log, ["shown overlay"]);
				assert.equal(s.shown.length, 1);
				const [{ component, options }] = s.overlays();
				assert.equal(options.overlayOptions.anchor, "center");
				const lines = plain(component.render(60));
				assert.ok(lines[1].startsWith("│  Diff for 'f.md'") && lines[2].startsWith("│ +body"));
				assert.ok(lines[0].trimStart().startsWith("╭─ Permission Required") && lines.at(-1)!.startsWith("╰"));
			});
		}

	test("shows a held ask with its own preview after the previous one closed", async () => {
		const s = await start(ORDERS[0]);
		await s.ask("r1");
		await settle();
		const hasBody = ({ component }: any) => plain(component.render(60)).some((line) => line.includes("+body"));
		const rendered = [hasBody(s.overlays()[0])];
		s.type("y");
		await s.emit("permissions:decision", { requestId: "r1" });
		await s.ask("r2");
		await sleep(250);
		rendered.push(hasBody(s.overlays()[1]));
		assert.deepEqual(s.log, ["shown overlay", "shown overlay"]);
		assert.deepEqual(rendered, [true, true]);
		assert.deepEqual([...previews.keys()], ["r2"]);
	});
});
