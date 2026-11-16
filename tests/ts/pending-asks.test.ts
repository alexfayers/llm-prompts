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

	test("each ASK line of a tool result is pinned once, and an error result pins nothing", async () => {
		const { ext, ctx, lastWidget } = await load();
		const result = (toolCallId: string, text: string, isError = false) => ext.fire("tool_result", { toolCallId, toolName: "bash", content: [{ type: "text", text }], isError }, ctx);
		await result("t1", "report\nASK: use A or B?\nnote ASK: inline\nASK: keep it?");
		await result("t2", "ASK: use A or B?");
		await result("t3", "ASK: broken?", true);
		assert.deepEqual(lastWidget(), ["Pending asks - /answer or ctrl+shift+a", "t1-1: use A or B?", "t1-2: keep it?"]);
	});

	test("the ASK lines of a fork or result_fetch result are left to the fork, which pins them itself", async () => {
		const { ext, ctx, lastWidget } = await load();
		for (const toolName of ["fork", "result_fetch"]) await ext.fire("tool_result", { toolCallId: toolName, toolName, content: [{ type: "text", text: "ASK: keep it?" }], isError: false }, ctx);
		assert.equal(lastWidget(), undefined);
	});


	test("an ASK line after an OUTCOME line came from a fork reply through another tool and is left to the fork", async () => {
		const { ext, ctx, lastWidget } = await load();
		await ext.fire("tool_result", { toolCallId: "t1", toolName: "codemode", content: [{ type: "text", text: "ASK: mine?\nOUTCOME found-it ref:x\nASK: the fork's?" }], isError: false }, ctx);
		assert.deepEqual(lastWidget(), ["Pending asks - /answer or ctrl+shift+a", "t1-1: mine?"]);
	});

	test("an answered ask_user call resolves the asks open before it, and a cancelled or failed one resolves none", async () => {
		const { ext, ctx, lastWidget } = await load();
		const askUser = async (toolCallId: string, details: object, isError = false) => {
			await ext.fire("tool_call", { toolCallId, toolName: "ask_user", input: {} }, ctx);
			await ext.fire("tool_result", { toolCallId, toolName: "ask_user", content: [{ type: "text", text: "answer" }], details, isError }, ctx);
		};
		await ext.callTool("asks", { action: "add", text: "pick a name" }, ctx);
		await askUser("u1", { cancelled: true });
		await askUser("u2", { cancelled: false }, true);
		assert.match(lastWidget()!.join("\n"), /pick a name/);
		await ext.fire("tool_call", { toolCallId: "u3", toolName: "ask_user", input: {} }, ctx);
		await ext.callTool("asks", { action: "add", text: "later" }, ctx);
		await ext.fire("tool_result", { toolCallId: "u3", toolName: "ask_user", content: [{ type: "text", text: "A" }], details: { cancelled: false }, isError: false }, ctx);
		assert.deepEqual(lastWidget(), ["Pending asks - /answer or ctrl+shift+a", "a2: later"]);
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

	test("reminds the model of open asks once every 5 user turns", async () => {
		const { ext, ctx } = await load();
		const branch: any[] = [];
		const reminded = ext.makeCtx({ ui: ctx.ui, sessionManager: { getBranch: () => branch } as any });
		const turn = async () => {
			const result = await ext.fire("before_agent_start", { prompt: "hi" }, reminded);
			branch.push({ type: "message", message: { role: "user" } });
			if (result) branch.push({ type: "custom_message", customType: result.message.customType });
			return result?.message;
		};
		assert.equal(await turn(), undefined);
		await ext.callTool("asks", { action: "add", text: "pick a name" }, reminded);
		branch.push(...ext.pi.appended.map(([customType, data]) => ({ type: "custom", customType, data })));
		for (let quiet = 0; quiet < 4; quiet++) assert.equal(await turn(), undefined);
		const message = await turn();
		assert.equal(message.content, "[asks] still open: a1. Resolve any you have answered, re-ask through ask_user any that block work, and leave the rest.");
		assert.equal(message.display, false);
		assert.equal(await turn(), undefined);
	});

	test("/answer <id> <text> sends the answer and resolves the ask", async () => {
		const { ext, ctx, lastWidget } = await load();
		await ext.callTool("asks", { action: "add", text: "pick a name" }, ctx);
		await ext.runCommand("answer", "a1 call it  Nova", ctx);
		assert.deepEqual(ext.pi.sent, [["Answer to a1: call it  Nova", { deliverAs: "followUp" }]]);
		assert.equal(lastWidget(), undefined);
	});
});
