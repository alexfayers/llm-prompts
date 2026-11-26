import assert from "node:assert/strict";
import { test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const spawned: { command: string; args: string[]; options: Record<string, unknown>; unref: boolean }[] = [];
function spawn(command: string, args: string[], options: Record<string, unknown>) {
	const child = { on: () => child, unref: () => (entry.unref = true) };
	const entry = { command, args, options, unref: false };
	spawned.push(entry);
	return child;
}
const load = () => loadExtension("session-telemetry", { mocks: { "node:child_process": { spawn } } });
const ext = await load();
useEnv({ PI_CONTEXT_ROLE: "writer" });

const usage = (input: number, cacheRead: number, cacheWrite: number, cost: number) => ({ input, output: 50, cacheRead, cacheWrite, totalTokens: input + cacheRead + cacheWrite + 50, cost: { total: cost } });
const reply = (u: ReturnType<typeof usage>) => ({ message: { role: "assistant", provider: "acme", model: "claude-opus-4-1", stopReason: "stop", usage: u } });

test("a session sends its totals once at its end, across a reload, and a session without calls sends nothing", async () => {
	await ext.fire("session_start", { reason: "startup" });
	await ext.fire("message_end", reply(usage(1000, 3000, 0, 0.25)));
	await ext.fire("message_end", { message: { role: "user", content: "secret prompt" } });
	await ext.fire("session_compact", { reason: "threshold" });
	await ext.fire("session_shutdown", { reason: "reload" });
	const reloaded = await load();
	await reloaded.fire("session_start", { reason: "reload" });
	await reloaded.fire("message_end", reply(usage(500, 1000, 500, 0.25)));
	await reloaded.fire("session_shutdown", { reason: "quit" });
	await reloaded.fire("session_start", { reason: "new" });
	await reloaded.fire("session_shutdown", { reason: "quit" });

	assert.equal(spawned.length, 1);
	const [{ command, args, options, unref }] = spawned;
	assert.deepEqual([command, args[0], options.detached, options.stdio, unref], ["llm-prompts", "session-telemetry", true, "ignore", true]);
	const { wallMs, ...stats } = JSON.parse(args[1]);
	assert.deepEqual(stats, { role: "writer", model: "acme/claude-opus-4-1", calls: 2, cost: 0.5, context: 6000, peak: 4000, cacheRead: 4000, compactions: 1 });
	assert.ok(wallMs >= 0);
});
