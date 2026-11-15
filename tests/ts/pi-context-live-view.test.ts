import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
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
	registry.start(run());
	background.attach("r1", { steer: async () => undefined, watch: (listener) => (listeners.push(listener), () => listeners.splice(0)) });
	for (const record of [
		{ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "looking" }], usage: { input: 1_000, cacheRead: 40_000, cacheWrite: 1_000, output: 500 } } },
		{ type: "tool_execution_start", toolName: "bash", args: { command: "ls" } },
	]) listeners.forEach((listener) => listener(record));
	const paint = { fg: (color: string, text: string) => `<${color}>${text}`, bold: (text: string) => `*${text}*` };
	const rendered = (widgets.at(-1) as any)(undefined, paint).render(200);
	assert.equal(rendered[0], "<dim>Background forks · /forks <name> for steps");
	background.view.window = 1_000_000;
	assert.equal(background.view.lines(66_000, paint)?.[1], "<accent>◑ <accent>*scout* <success>[reader] <dim>1m05s · 1 turn<dim> · ctx 43k/1M · <dim>cache 95%  <muted>bash: ls");
	listeners.forEach((listener) => listener({ type: "message_end", message: { role: "assistant", content: [], usage: { input: 30_000, cacheRead: 10_000 } } }));
	assert.match(background.view.lines(66_000, paint)?.[1] ?? "", /<error>cache 25%/);
	assert.ok(background.view.lines(66_000, paint, 20)?.every((line) => line.length < 40));
	registry.update("r1", { state: "done" });
	assert.equal(widgets.at(-1), undefined);
	assert.equal(listeners.length, 0);
});

test("/forks lists the forks, and /forks <name> shows a fork's own steps from its session file", async () => {
	const files = fs.mkdtempSync(path.join(os.tmpdir(), "live-view-"));
	const entry = (timestamp: string, content: unknown[], usage?: unknown) => JSON.stringify({ type: "message", timestamp, message: { role: "assistant", content, usage } });
	fs.writeFileSync(path.join(files, "seed.jsonl"), [entry("1970-01-01T00:00:00.500Z", [{ type: "text", text: "main's own history" }]), entry("1970-01-01T00:00:02Z", [{ type: "text", text: "checking" }, { type: "toolCall", name: "read", arguments: { path: "a.ts" } }], { input: 100, cacheRead: 900 })].join("\n"));
	const registry = new Registry();
	registry.start(run({ files, state: "done", endedAt: 3_000 }));
	let command: any;
	registerLiveView({ on: () => undefined, registerCommand: (_name: string, spec: any) => (command = spec) } as any, new LiveView(registry), registry);
	const notes: string[] = [];
	const ctx = { hasUI: true, ui: { notify: (text: string) => notes.push(text), theme: { fg: (_color: string, text: string) => text } }, sessionManager: { getBranch: () => [] } };
	await command.handler("", ctx);
	await command.handler("scout", ctx);
	assert.deepEqual(notes, ["scout done 2s", 'scout (reader, done, ctx 1k, cache 90%)\n  checking\n> read: a.ts']);
});

test("a widget whose session ended stops listening, so a reload's stale context cannot break the next fork", () => {
	const registry = new Registry();
	const handlers = new Map<string, (...args: any[]) => void>();
	registerLiveView({ on: (event: string, handler: any) => handlers.set(event, handler), registerCommand: () => undefined } as any, new LiveView(registry), registry);
	let stale = false;
	handlers.get("session_start")?.({}, { hasUI: true, ui: { setWidget: () => { if (stale) throw new Error("stale ctx"); } } });
	stale = true;
	handlers.get("session_shutdown")?.({});
	assert.doesNotThrow(() => registry.start(run()));
});
