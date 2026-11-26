import assert from "node:assert/strict";
import { test } from "node:test";
import { Background } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/background.ts";
import { LiveView, registerLiveView } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/live-view.ts";
import { Registry, type Run } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";

delete process.env.PI_CONTEXT_CHILD;
delete process.env.PI_CACHE_RETENTION;

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
	assert.equal(background.view.lines(66_000, paint)?.[1], "<accent>◑ <accent>*scout* <success>[reader] <dim>1m05s · 1 turn · feature-branch  <muted>bash: git diff --stat");
	listeners.forEach((listener) => listener({ type: "message_end", message: { role: "assistant", content: [], usage: { input: 30_000, cacheRead: 10_000 } } }));
	assert.match(background.view.lines(66_000, paint)?.[1] ?? "", /<error> · cache 25%/);
	listeners.forEach((listener) => listener({ type: "message_end", message: { role: "assistant", content: [], usage: { input: 100_000, cacheRead: 500_000 } } }));
	assert.match(background.view.lines(66_000, paint)?.[1] ?? "", /<warning> · ctx 600k\/1M/);
	assert.ok(background.view.lines(66_000, paint, 20)?.every((line) => line.length < 40));
	registry.start(run({ id: "r2", name: "cold-one", model: "prov/anthropic.claude-opus-5-5:medium" }));
	assert.match(background.view.lines(66_000, paint)?.[2] ?? "", /<muted>\[opus\]/);
	registry.update("r2", { state: "done" });
	registry.update("r1", { state: "done" });
	assert.equal(widgets.at(-1), undefined);
	assert.equal(listeners.length, 0);
});

test("finished forks fold into one summary row, each count in its outcome's color, while live forks keep their own rows", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	for (const id of ["l1", "l2", "l3"]) registry.start(run({ id, name: id }));
	const states: Run["state"][] = ["done", "done", "done", "done", "done", "done", "done", "done", "found-it", "found-it", "blocked", "failed"];
	states.forEach((state, index) => registry.start(run({ id: `f${index}`, name: `f${index}`, state, lastRequestAt: 1_000 + index * 10_000, unread: "r" })));
	const lines = view.lines(62_000) ?? [];
	assert.equal(lines.length, 5);
	assert.equal(lines[4], "\u2713 8 done \u00b7 2 found-it \u00b7 1 blocked \u00b7 1 failed \u00b7 cache 4-6m");
	const paint = { fg: (color: string, text: string) => `<${color}>${text}`, bold: (text: string) => `*${text}*` };
	assert.equal(view.lines(62_000, paint)?.[4], "<dim>\u2713 <success>8 done<dim> \u00b7 <success>2 found-it<dim> \u00b7 <warning>1 blocked<dim> \u00b7 <error>1 failed<dim> \u00b7 cache 4-6m");
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
	const asks = ["fork-pending-b2-1"];
	assert.deepEqual(view.lines(2_000, paint, Number.POSITIVE_INFINITY, asks)?.slice(1).map((line) => line.split(" ")[1]), ["pending"]);
	registry.update("b2", { unread: "r" });
	registry.start(run({ id: "d1", name: "unasked", state: "done", lastRequestAt: 1_000, unread: "r" }));
	assert.deepEqual(view.lines(2_000, paint, Number.POSITIVE_INFINITY, asks)?.slice(1), ["\u25cf pending [reader] blocked \u00b7 cache 5m", "\u2713 1 done \u00b7 cache 5m"]);
});

test("a fork leaves the widget once its result reaches main, whatever its outcome, and returns while an aborted run re-announces it", () => {
	const registry = new Registry();
	const background = new Background({ sendMessage: () => undefined, appendEntry: () => undefined } as any, registry);
	const view = new LiveView(registry, (run) => background.received(run));
	const ctx = { isIdle: () => false, hasUI: false, sessionManager: { getBranch: () => [] } } as any;
	for (const [name, state] of [["d", "done"], ["f", "found-it"], ["b", "blocked"], ["x", "failed"]] as const) {
		registry.start(run({ id: name, name }));
		background.finish(ctx, name, { state, lastRequestAt: Date.now() }, `OUTCOME ${state} ref:rc`);
	}
	assert.equal(view.lines(), undefined);
	background.settle(ctx, true);
	assert.equal(view.lines()?.length, 2);
	assert.equal(background.digest()?.split("\n").length, 5);
	assert.equal(view.lines(), undefined);
	background.settle(ctx, false);
	assert.equal(view.lines(), undefined);
});

test("a read failed fork stays while one of its asks is open, with no request to cache", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	registry.start(run({ id: "x1", name: "broken", state: "failed" }));
	assert.deepEqual(view.lines(2_000, undefined, Number.POSITIVE_INFINITY, ["fork-broken-x1-1"])?.slice(1).map((line) => line.split(" ")[1]), ["broken"]);
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
		"◓ api-scan [cheap:low] 1m45s · 0 turns · from stub-ab12",
		"◓ docs-scan [cheap:low] 1m45s · 0 turns · from stub-ab12",
		"◓ fix-widget [writer] 2m00s · 0 turns · fix-widget",
		"\u2713 1 done \u00b7 1 failed \u00b7 cache 4m",
	]);
});

test("two sources that share a name are told apart by their cache key", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	for (const [id, key] of [["a", "3f9a2c11"], ["b", "3f9a2c11"], ["c", "77b0de42"]]) registry.start(run({ id, name: `kid-${id}`, from: "stub", cacheKey: key }));
	registry.start(run({ id: "d", name: "kid-d", from: "other", cacheKey: "0000aa" }));
	assert.deepEqual(view.lines(2_000)?.slice(1).map((line) => line.split(" · ").at(-1)), ["from stub#3f9a2c", "from stub#3f9a2c", "from stub#77b0de", "from other"]);
});

test("the widget scans the session for open asks once per branch change, not per run or per frame", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	for (let index = 0; index < 20; index++) registry.start(run({ id: `f${index}`, name: `f${index}`, state: "done", lastRequestAt: Date.now(), unread: "r" }));
	let scans = 0;
	let leaf = "a";
	const entries = [{ type: "custom", customType: "pending-asks", data: { action: "add", id: "fork-f0-f0-1", text: "which?" } }];
	const widgets: any[] = [];
	view.bind({ hasUI: true, ui: { setWidget: (_key: string, widget?: unknown) => widgets.push(widget) }, sessionManager: { getLeafId: () => leaf, getBranch: () => (scans++, entries) } } as any);
	const paint = { fg: (_color: string, text: string) => text, bold: (text: string) => text };
	const frames = () => Array.from({ length: 5 }, () => widgets.at(-1)(undefined, paint).render(200)).at(-1);
	assert.deepEqual(frames().slice(1).map((line: string) => line.split(" ")[1]), ["f0", "19"]);
	assert.equal(scans, 1);
	registry.update("f1", { unread: "r2" });
	frames();
	assert.equal(scans, 1);
	leaf = "b";
	view.refresh();
	assert.equal(scans, 2);
	view.release();
});

test("a fork row with a long command fits in 100 columns and shows the tool with a 40 character command", () => {
	const registry = new Registry();
	const view = new LiveView(registry);
	const listeners: ((record: any) => void)[] = [];
	const background = new Background({ sendMessage: () => undefined } as any, registry);
	background.view = view;
	registry.start(run({ id: "w", name: "w-795", model: "global.anthropic.claude-sonnet-5-5", target: "/repo/worktrees/audit-npm-log" }));
	background.attach("w", { steer: async () => undefined, watch: (listener) => (listeners.push(listener), () => undefined) });
	listeners.forEach((listener) => listener({ type: "tool_execution_start", toolName: "bash", args: { command: "git switch -c alexfayers/audit-npm-log -q && git add -A && git commit -m x" } }));
	const row = view.lines(276_000)?.[1] ?? "";
	assert.equal(row, "◐ w-795 [sonnet] 4m35s · 0 turns · audit-npm-log  bash: git switch -c alexfayers/audit-npm-lo...");
	assert.ok(row.length <= 100);
});
