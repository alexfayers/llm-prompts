import assert from "node:assert/strict";
import { test } from "node:test";
import { Background } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/background.ts";
import { LiveView } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/live-view.ts";
import { Registry } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";

delete process.env.PI_CONTEXT_CHILD;

const ENTRIES = 25_000;
const FINISHED_RUNS = 500;
const FRAMES = 20;

const message = (index: number) => ({ type: "message", message: { role: "assistant", usage: { input: 1, output: 1, totalTokens: index } } });
const askEntry = (run: { id: string; name: string }) => ({ type: "custom", customType: "pending-asks", data: { action: "add", id: `fork-${run.name}-${run.id}-1`, text: "which?" } });

/** A session of 25,000 entries with 500 finished runs, each with an open ask, that counts how often the branch is read. */
const session = () => {
	const registry = new Registry();
	const runs = Array.from({ length: FINISHED_RUNS }, (_, index) => ({ id: `r${index}`, name: `run${index}`, role: "reader", background: true, state: "done" as const, task: "t", startedAt: 1_000, endedAt: 2_000 + index, unread: `[fork run${index}] done` }));
	runs.forEach((run) => registry.start(run));
	const entries: object[] = [...Array.from({ length: ENTRIES - FINISHED_RUNS }, (_, index) => message(index)), ...runs.map(askEntry)];
	const widgets: any[] = [];
	const state = { scans: 0, leaf: "a" };
	const view = new LiveView(registry);
	view.bind({ hasUI: true, ui: { setWidget: (_key: string, widget?: unknown) => widgets.push(widget) }, sessionManager: { getLeafId: () => state.leaf, getBranch: () => (state.scans++, entries) } } as any);
	return { registry, view, widgets, state };
};

test("the widget scans the session once per branch change across many frames and run updates", () => {
	const { registry, view, widgets, state } = session();
	const paint = { fg: (_color: string, text: string) => text, bold: (text: string) => text };
	for (let frame = 0; frame < FRAMES; frame++) {
		registry.update(`r${frame}`, { unread: `[fork run${frame}] again` });
		widgets.at(-1)(undefined, paint).render(200);
	}
	assert.equal(widgets.at(-1)(undefined, paint).render(200).length, FINISHED_RUNS + 1);
	assert.equal(state.scans, 1);
	state.leaf = "b";
	view.refresh();
	assert.equal(state.scans, 2);
	view.release();
});

test("the results digest scans the session once per branch change across many digests", () => {
	const { registry, view, state } = session();
	const background = new Background({ sendMessage: () => undefined } as any, registry);
	background.view = view;
	const digested = background.digest();
	assert.equal(digested?.split("\n").length, FINISHED_RUNS + 1);
	for (let digest = 0; digest < FRAMES; digest++) {
		registry.update(`r${digest}`, { unread: `[fork run${digest}] again` });
		background.digest();
	}
	assert.equal(state.scans, 1);
	view.release();
});
