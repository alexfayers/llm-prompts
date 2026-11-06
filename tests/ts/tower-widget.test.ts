import assert from "node:assert/strict";
import { test } from "node:test";
import { loadExtension } from "./helpers.ts";

const KEY = "pi-tower-do-widget";

async function startSession() {
	const calls: [string, unknown][] = [];
	const ext = await loadExtension("tower-widget");
	ext.ctx.ui.setWidget = (key: string, content: unknown) => void calls.push([key, content]);
	await ext.fire("session_start");
	return { ext, calls, lastWidget: () => calls.filter(([key]) => key === KEY).at(-1)?.[1] };
}

test("tower-do widget updates are replaced by a clear by default", async () => {
	const { ext, lastWidget } = await startSession();
	ext.ctx.ui.setWidget(KEY, (() => ({})) as any, { placement: "aboveEditor" });
	assert.equal(lastWidget(), undefined);
});

test("other widgets pass through", async () => {
	const { ext, lastWidget, calls } = await startSession();
	ext.ctx.ui.setWidget("other", ["x"]);
	assert.deepEqual(calls.at(-1), ["other", ["x"]]);
	assert.equal(lastWidget(), undefined);
});

test("the command shows the latest widget and hides it again", async () => {
	const { ext, lastWidget } = await startSession();
	const factory = (() => ({})) as any;
	ext.ctx.ui.setWidget(KEY, factory);
	await ext.runCommand("tower-widget");
	assert.equal(lastWidget(), factory);
	ext.ctx.ui.setWidget(KEY, undefined);
	assert.equal(lastWidget(), undefined);
	await ext.runCommand("tower-widget");
	assert.equal(lastWidget(), undefined);
});
