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
	const { wallMs, inferenceMs, commandMs, userMs, ...stats } = JSON.parse(args[1]);
	assert.deepEqual(stats, { role: "writer", model: "acme/claude-opus-4-1", calls: 2, cost: 0.5, context: 6000, peak: 4000, cacheRead: 4000, compactions: 1 });
	assert.ok(wallMs >= inferenceMs + commandMs + userMs);
});

test("a session splits its wall time into model calls, tool calls and user waits", async (t) => {
	spawned.length = 0;
	let now = 1_000_000;
	t.mock.method(Date, "now", () => now);
	const at = async (seconds: number, event: string, payload: unknown = {}) => {
		now = 1_000_000 + seconds * 1000;
		await ext.fire(event, payload);
	};
	const start = (toolCallId: string, toolName: string, command = "") => ({ toolCallId, toolName, args: { command } });
	const end = (toolCallId: string, toolName: string, text = "", isError = false) => ({ toolCallId, toolName, isError, result: { content: [{ type: "text", text }] } });
	await at(0, "session_start", { reason: "startup" });
	await at(8, "input", { source: "interactive", text: "go" });
	await at(8, "agent_start");
	await at(9, "before_provider_request");
	await at(9.5, "before_provider_request");
	await at(10, "message_start", { message: { role: "assistant" } });
	await at(14, "message_end", reply(usage(1000, 0, 0, 0.1)));
	await at(14, "tool_execution_start", start("a", "bash", "gh pr create --draft --title x"));
	await at(16, "tool_execution_start", start("b", "bash", "gh pr create --help"));
	await at(18, "tool_execution_start", start("c", "ask_user"));
	await at(20, "tool_execution_end", end("a", "bash", "https://github.com/octo/widgets/pull/12"));
	await at(22, "tool_execution_end", end("b", "bash", "Usage: gh pr create"));
	await at(24, "tool_execution_end", end("c", "ask_user", "yes"));
	await at(24, "tool_execution_start", start("d", "bash", "ls"));
	await at(25, "ui_prompt_start", { reason: "ui_prompt", kind: "confirm" });
	await at(28, "ui_prompt_end");
	await at(30, "tool_execution_end", end("d", "bash", "a.txt"));
	await at(30, "before_provider_request");
	await at(33, "message_end", reply(usage(1000, 0, 0, 0.1)));
	await at(33, "agent_settled");
	await at(36, "input", { source: "extension", text: "fork done" });
	await at(36, "agent_start");
	await at(37, "before_provider_request");
	await at(39, "message_end", reply(usage(1000, 0, 0, 0.1)));
	await at(39, "agent_settled");
	await at(45, "session_shutdown", { reason: "quit" });

	assert.equal(spawned.length, 1);
	const { wallMs, inferenceMs, commandMs, userMs } = JSON.parse(spawned[0].args[1]);
	assert.deepEqual({ wallMs, inferenceMs, commandMs, userMs }, { wallMs: 45000, inferenceMs: 10000, commandMs: 7000, userMs: 17000 });
});

test("a request while idle or while a tool runs, or one cut off by a compaction, adds no model time", async (t) => {
	spawned.length = 0;
	let now = 1_000_000;
	t.mock.method(Date, "now", () => now);
	const at = async (seconds: number, event: string, payload: unknown = {}) => {
		now = 1_000_000 + seconds * 1000;
		await ext.fire(event, payload);
	};
	const tool = { toolCallId: "a", toolName: "bash", args: { command: "just" } };
	await at(0, "session_start", { reason: "startup" });
	await at(2, "input", { source: "interactive", text: "go" });
	await at(2, "agent_start");
	await at(2, "before_provider_request");
	await at(4, "message_end", reply(usage(1000, 0, 0, 0.1)));
	await at(4, "tool_execution_start", tool);
	await at(6, "before_provider_request");
	await at(8, "tool_execution_end", { ...tool, isError: false, result: { content: [] } });
	await at(8, "before_provider_request");
	await at(9, "session_compact", { reason: "overflow" });
	await at(10, "before_provider_request");
	await at(11, "message_end", reply(usage(1000, 0, 0, 0.1)));
	await at(11, "agent_settled");
	await at(20, "before_provider_request");
	await at(30, "input", { source: "interactive", text: "more" });
	await at(30, "agent_start");
	await at(31, "before_provider_request");
	await at(32, "message_end", reply(usage(1000, 0, 0, 0.1)));
	await at(32, "agent_settled");
	await at(32, "session_shutdown", { reason: "quit" });

	const { wallMs, inferenceMs, commandMs, userMs } = JSON.parse(spawned[0].args[1]);
	assert.deepEqual({ wallMs, inferenceMs, commandMs, userMs }, { wallMs: 32000, inferenceMs: 4000, commandMs: 4000, userMs: 21000 });
});

test("a nested tool call that never ends does not keep the tool clock running", async (t) => {
	spawned.length = 0;
	let now = 1_000_000;
	t.mock.method(Date, "now", () => now);
	const at = async (seconds: number, event: string, payload: unknown = {}) => {
		now = 1_000_000 + seconds * 1000;
		await ext.fire(event, payload);
	};
	const parent = { toolCallId: "a", toolName: "codemode", args: {} };
	await at(0, "session_start", { reason: "startup" });
	await at(0, "input", { source: "interactive", text: "go" });
	await at(0, "agent_start");
	await at(0, "before_provider_request");
	await at(2, "message_end", reply(usage(1000, 0, 0, 0.1)));
	await at(2, "tool_execution_start", parent);
	await at(3, "tool_execution_start", { toolCallId: "b", toolName: "bash", args: { command: "ls" }, parentToolCallId: "a" });
	await at(5, "tool_execution_end", { ...parent, isError: true, result: { content: [] } });
	await at(6, "before_provider_request");
	await at(8, "message_end", reply(usage(1000, 0, 0, 0.1)));
	await at(8, "agent_settled");
	await at(8, "session_shutdown", { reason: "quit" });

	const { wallMs, inferenceMs, commandMs, userMs } = JSON.parse(spawned[0].args[1]);
	assert.deepEqual({ wallMs, inferenceMs, commandMs, userMs }, { wallMs: 8000, inferenceMs: 4000, commandMs: 3000, userMs: 0 });
});
