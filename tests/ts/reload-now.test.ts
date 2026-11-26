import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const RELOAD = ["/reload-now", { expandPromptTemplates: true }];

const CONTINUE = "Reload finished. Continue the task. If nothing is open, reply with one emoji.";

useEnv({ PI_CONTEXT_CHILD: "" });

type Loaded = Awaited<ReturnType<typeof loadExtension>>;

async function runCommand(ext: Loaded, idle: boolean, loadNew = true) {
	const copies: Loaded[] = [];
	let reloads = 0;
	const reload = async () => {
		reloads++;
		if (!loadNew) return;
		const copy = await loadExtension("reload-now");
		copies.push(copy);
		await copy.fire("session_start", { reason: "reload" }, copy.ctx);
	};
	await ext.runCommand("reload-now", "", ext.makeCtx({ isIdle: () => idle, reload }));
	return { copies, reloads };
}

describe("reload_now", () => {
	test("reloads after the turn settles, once", async () => {
		const ext = await loadExtension("reload-now");
		const result = await ext.callTool("reload_now");
		assert.equal(result.terminate, true);
		assert.deepEqual(ext.pi.sent, []);
		await ext.fire("agent_settled", { aborted: false });
		await ext.fire("agent_settled", { aborted: false });
		assert.deepEqual(ext.pi.sent, [RELOAD]);
	});

	test("a delegate can neither call it nor run the command", async () => {
		process.env.PI_CONTEXT_CHILD = "/tmp/handshake.json";
		const ext = await loadExtension("reload-now");
		await assert.rejects(ext.callTool("reload_now"), /delegate/);
		await ext.fire("agent_settled", { aborted: false });
		assert.deepEqual(ext.pi.sent, []);
		const { reloads } = await runCommand(ext, true);
		assert.equal(reloads, 0);
	});

	test("the command marks the reload as requested while it runs", async () => {
		const ext = await loadExtension("reload-now");
		const requested = Symbol.for("llm-prompts.reload-now.requested");
		let during: unknown;
		await ext.runCommand("reload-now", "", ext.makeCtx({ isIdle: () => true, reload: async () => void (during = (globalThis as any)[requested]) }));
		assert.equal(during, true);
		assert.equal((globalThis as any)[requested], undefined);
	});

	test("the command reloads, then the new copy continues the task", async () => {
		const ext = await loadExtension("reload-now");
		const { copies: [copy] } = await runCommand(ext, true);
		assert.deepEqual(copy.pi.sent, [[CONTINUE]]);
		assert.deepEqual(ext.pi.sent, []);
	});
});
