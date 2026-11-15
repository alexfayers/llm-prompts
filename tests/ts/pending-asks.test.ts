import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

async function load() {
	const ext = await loadExtension("pending-asks");
	const widgets: [string, string[] | undefined][] = [];
	const entries = () => ext.pi.appended.map(([customType, data]) => ({ type: "custom", customType, data }));
	const ctx = ext.makeCtx({
		ui: { notify: (message: string, level?: string) => ctx.notices.push([message, level]), setWidget: (key: string, lines?: string[]) => widgets.push([key, lines]) },
		sessionManager: { getBranch: entries } as any,
	});
	return { ext, ctx, widgets, lastWidget: () => widgets.at(-1)?.[1] };
}

describe("pending asks", () => {
	test("add then resolve folds the queue and updates the widget", async () => {
		const { ext, ctx, lastWidget } = await load();
		assert.match((await ext.callTool("asks", { action: "add", text: "pick a name" }, ctx)).content[0].text, /a1 pinned/);
		await ext.callTool("asks", { action: "add", text: "ok to push?" }, ctx);
		assert.deepEqual(ext.module.openAsks(ext.pi.appended.map(([customType, data]) => ({ type: "custom", customType, data }))).map((ask: any) => ask.id), ["a1", "a2"]);
		assert.match(lastWidget()!.join("\n"), /a1.*pick a name[\s\S]*a2.*ok to push/);
		assert.match((await ext.callTool("asks", { action: "resolve", id: "a1" }, ctx)).content[0].text, /a1 resolved/);
		assert.doesNotMatch(lastWidget()!.join("\n"), /pick a name/);
		await ext.callTool("asks", { action: "add", text: "third" }, ctx);
		assert.match(lastWidget()!.join("\n"), /a3.*third/);
	});

	test("/asks lists the queue without a model call", async () => {
		const { ext, ctx } = await load();
		await ext.runCommand("asks", "", ctx);
		assert.match(ctx.notices.at(-1)![0], /no pending asks/i);
		await ext.callTool("asks", { action: "add", text: "pick a name" }, ctx);
		await ext.runCommand("asks", "", ctx);
		assert.match(ctx.notices.at(-1)![0], /a1.*pick a name/);
		assert.deepEqual(ext.pi.sent, []);
	});

	test("without a UI nothing is drawn", async () => {
		const { ext, widgets } = await load();
		const headless = ext.makeCtx({ hasUI: false, ui: { setWidget: () => widgets.push(["x", []]) } as any });
		await ext.callTool("asks", { action: "add", text: "q" }, headless);
		await ext.fire("session_start", {}, headless);
		assert.deepEqual(widgets, []);
	});

	test("without a UI the restate rule is injected once per branch", async () => {
		const { ext } = await load();
		const branch: unknown[] = [];
		const headless = ext.makeCtx({ hasUI: false, sessionManager: { getBranch: () => branch } as any });
		const first = await ext.fire("before_agent_start", { prompt: "hi" }, headless);
		assert.match(first.message.content, /MUST restate EVERY pending ask/);
		assert.equal(first.message.display, false);
		branch.push({ type: "custom_message", customType: first.message.customType });
		assert.equal(await ext.fire("before_agent_start", { prompt: "again" }, headless), undefined);
		assert.equal(await ext.fire("before_agent_start", { prompt: "hi" }, (await load()).ctx), undefined);
	});
});
