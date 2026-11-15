import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const RELOAD = ["/reload-now", { expandPromptTemplates: true }];

const CONTINUE = "Reload finished. Continue the task. If nothing is open, reply with one emoji.";

useEnv({ PI_HERDSMAN_MAILBOX: "" });

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

	test("a managed agent can neither call it nor run the command", async () => {
		process.env.PI_HERDSMAN_MAILBOX = "m";
		const ext = await loadExtension("reload-now");
		await assert.rejects(ext.callTool("reload_now"), /managed agent/);
		await ext.fire("agent_settled", { aborted: false });
		assert.deepEqual(ext.pi.sent, []);
		const { reloads } = await runCommand(ext, true);
		assert.equal(reloads, 0);
	});

	test("neither the tool nor the command reloads while a background fork is live", async () => {
		const key = Symbol.for("pi-context.registry");
		(globalThis as any)[key] = { live: () => [{ name: "a", background: true }, { name: "fg", background: false }, { name: "b", background: true }] };
		try {
			const ext = await loadExtension("reload-now");
			await assert.rejects(ext.callTool("reload_now"), /background forks a, b are still running.*fork_cancel/);
			await ext.fire("agent_settled", { aborted: false });
			assert.deepEqual(ext.pi.sent, []);
			const { reloads } = await runCommand(ext, true);
			assert.equal(reloads, 0);
		} finally {
			delete (globalThis as any)[key];
		}
	});

	test("the command reloads, then the new copy continues the task", async () => {
		const ext = await loadExtension("reload-now");
		const { copies: [copy] } = await runCommand(ext, true);
		assert.deepEqual(copy.pi.sent, [[CONTINUE]]);
		assert.deepEqual(ext.pi.sent, []);
	});
});
