import assert from "node:assert/strict";
import { test } from "node:test";
import { Background } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/background.ts";
import { LiveView, registerLiveView } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/live-view.ts";
import { Registry, type Run } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";

delete process.env.PI_CONTEXT_CHILD;

const run = (patch: Partial<Run> = {}): Run => ({ id: "r1", name: "scout", role: "reader", background: true, state: "running", task: "t", startedAt: 1_000, ...patch });

test("the widget follows a background fork's events and clears when it ends", () => {
	const registry = new Registry();
	const background = new Background({ sendMessage: () => undefined } as any, registry);
	background.view = new LiveView(registry);
	const widgets: unknown[] = [];
	background.view.bind({ hasUI: true, ui: { setWidget: (_key: string, widget?: unknown) => widgets.push(widget) } } as any);
	const listeners: ((record: any) => void)[] = [];
	registry.start(run({ target: "/repo/worktrees/feature-branch" }));
	background.attach("r1", { steer: async () => undefined, watch: (listener) => (listeners.push(listener), () => listeners.splice(0)) });
	for (const record of [
		{ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "looking" }], usage: { input: 1_000, cacheRead: 40_000, cacheWrite: 1_000, output: 500 } } },
		{ type: "tool_execution_start", toolName: "bash", args: { command: "cd /repo/worktrees/feature-branch && git diff --stat" } },
	]) listeners.forEach((listener) => listener(record));
	const paint = { fg: (color: string, text: string) => `<${color}>${text}`, bold: (text: string) => `*${text}*` };
	const rendered = (widgets.at(-1) as any)(undefined, paint).render(200);
	assert.equal(rendered[0], "<dim>Background forks");
	background.view.window = 1_000_000;
	assert.equal(background.view.lines(66_000, paint)?.[1], "<accent>◑ <accent>*scout* <success>[reader] <dim>1m05s · 1 turn · feature-branch<dim> · ctx 43k/1M · <dim>cache 95%  <muted>bash: git diff --stat");
	listeners.forEach((listener) => listener({ type: "message_end", message: { role: "assistant", content: [], usage: { input: 30_000, cacheRead: 10_000 } } }));
	assert.match(background.view.lines(66_000, paint)?.[1] ?? "", /<error>cache 25%/);
	assert.ok(background.view.lines(66_000, paint, 20)?.every((line) => line.length < 40));
	registry.start(run({ id: "r2", name: "cold-one", model: "prov/anthropic.claude-opus-5-5:medium" }));
	assert.match(background.view.lines(66_000, paint)?.[2] ?? "", /<muted>\[cold claude-opus-5-5:medium\]/);
	registry.update("r2", { state: "done" });
	registry.update("r1", { state: "done" });
	assert.equal(widgets.at(-1), undefined);
	assert.equal(listeners.length, 0);
});

test("a finished run's glyph color follows its outcome, while its prompt cache is warm", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	const paint = { fg: (color: string, text: string) => `<${color}>${text}`, bold: (text: string) => `*${text}*` };
	const states: [Run["state"], string][] = [["done", "success"], ["found-it", "success"], ["blocked", "warning"], ["failed", "error"]];
	states.forEach(([state], index) => registry.start(run({ id: `f${index}`, name: `f${index}`, state, lastRequestAt: 1_000, unread: "r" })));
	states.forEach(([, color], index) => assert.match(view.lines(2_000, paint)?.[index + 1] ?? "", new RegExp(`^<${color}>\u25cf`)));
});

test("a widget whose session ended stops listening, so a reload's stale context cannot break the next fork", () => {
	const registry = new Registry();
	const handlers = new Map<string, (...args: any[]) => void>();
	registerLiveView({ on: (event: string, handler: any) => handlers.set(event, handler) } as any, new LiveView(registry));
	let stale = false;
	handlers.get("session_start")?.({}, { hasUI: true, ui: { setWidget: () => { if (stale) throw new Error("stale ctx"); } } });
	stale = true;
	handlers.get("session_shutdown")?.({});
	assert.doesNotThrow(() => registry.start(run()));
});

test("a read blocked fork leaves the widget once its asks are answered, but stays while one is open", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	const paint = { fg: (_color: string, text: string) => text, bold: (text: string) => text };
	registry.start(run({ id: "b1", name: "answered", state: "blocked", lastRequestAt: 1_000 }));
	registry.start(run({ id: "b2", name: "pending", state: "blocked", lastRequestAt: 1_000 }));
	const entries = [{ type: "custom", customType: "pending-asks", data: { action: "add" as const, id: "fork-pending-b2-1", text: "which one?" } }];
	assert.deepEqual(view.lines(2_000, paint, Number.POSITIVE_INFINITY, entries)?.slice(1).map((line) => line.split(" ")[1]), ["pending"]);
});

test("a done or found-it fork, or a read blocked one with no open ask, leaves the widget, while a failed one stays", () => {
	const registry = new Registry();
	const background = new Background({ sendMessage: () => undefined, appendEntry: () => undefined } as any, registry);
	const view = new LiveView(registry);
	const ctx = { isIdle: () => false, hasUI: false } as any;
	for (const [name, state] of [["d", "done"], ["f", "found-it"], ["b", "blocked"], ["x", "failed"]] as const) {
		registry.start(run({ id: name, name }));
		background.finish(ctx, name, { state, lastRequestAt: Date.now() }, `OUTCOME ${state} ref:rc`);
	}
	assert.equal(view.lines()?.length, 5);
	background.digest();
	assert.deepEqual(view.lines()?.slice(1).map((line) => line.split(" ")[1]), ["x"]);
});
