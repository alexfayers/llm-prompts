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

test("a fork leaves the widget once main has read its result, whatever its outcome", () => {
	const registry = new Registry();
	const background = new Background({ sendMessage: () => undefined, appendEntry: () => undefined } as any, registry);
	const view = new LiveView(registry);
	const ctx = { isIdle: () => false, hasUI: false, sessionManager: { getBranch: () => [] } } as any;
	for (const [name, state] of [["d", "done"], ["f", "found-it"], ["b", "blocked"], ["x", "failed"]] as const) {
		registry.start(run({ id: name, name }));
		background.finish(ctx, name, { state, lastRequestAt: Date.now() }, `OUTCOME ${state} ref:rc`);
	}
	assert.equal(view.lines()?.length, 5);
	background.digest();
	assert.equal(view.lines()?.length, 5);
	background.settle(ctx, true);
	assert.equal(view.lines()?.length, 5);
	assert.equal(background.digest()?.split("\n").length, 4);
	background.settle(ctx, false);
	assert.equal(view.lines(), undefined);
});

test("a read failed fork stays while one of its asks is open, with no request to cache", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	registry.start(run({ id: "x1", name: "broken", state: "failed" }));
	const entries = [{ type: "custom", customType: "pending-asks", data: { action: "add" as const, id: "fork-broken-x1-1", text: "retry?" } }];
	assert.deepEqual(view.lines(2_000, undefined, Number.POSITIVE_INFINITY, entries)?.slice(1).map((line) => line.split(" ")[1]), ["broken"]);
	assert.equal(view.lines(2_000), undefined);
});

test("forks started from the same source show it, and a fork with none shows nothing", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	const fork = (patch: Partial<Run>) => registry.start(run({ role: "reader", model: "prov/cheap:low", from: "stub-ab12", startedAt: 20_000, ...patch }));
	fork({ id: "a", name: "api-scan" });
	fork({ id: "b", name: "docs-scan" });
	fork({ id: "c", name: "fix-widget", role: "writer", model: undefined, from: undefined, startedAt: 5_000, target: "/repo/worktrees/fix-widget" });
	fork({ id: "d", name: "tests-scan", state: "failed", lastRequestAt: 60_000, unread: "r" });
	fork({ id: "e", name: "review", state: "done", model: undefined, from: undefined, lastRequestAt: 60_000, unread: "r" });
	assert.deepEqual(view.lines(125_000), [
		"Background forks",
		"◓ api-scan [cold cheap:low] 1m45s · 0 turns · from stub-ab12",
		"◓ docs-scan [cold cheap:low] 1m45s · 0 turns · from stub-ab12",
		"◓ fix-widget [writer] 2m00s · 0 turns · fix-widget",
		"● tests-scan [cold cheap:low] failed · cache 59m left · from stub-ab12",
		"● review [reader] done · cache 59m left",
	]);
});

test("two sources that share a name are told apart by their cache key", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	for (const [id, key] of [["a", "3f9a2c11"], ["b", "3f9a2c11"], ["c", "77b0de42"]]) registry.start(run({ id, name: `kid-${id}`, from: "stub", cacheKey: key }));
	registry.start(run({ id: "d", name: "kid-d", from: "other", cacheKey: "0000aa" }));
	assert.deepEqual(view.lines(2_000)?.slice(1).map((line) => line.split(" · ").at(-1)), ["from stub#3f9a2c", "from stub#3f9a2c", "from stub#77b0de", "from other"]);
});
