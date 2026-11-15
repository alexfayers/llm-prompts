import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const wake = (customType = "pi-herdsman-agent-result") => ({ messageType: "custom", message: { customType } });
const user = (prompt = "next") => ({ messageType: "user", prompt });

const reply = (cacheRead: number) => ({ type: "message", message: { role: "assistant", usage: { input: 1, output: 1, cacheRead, cacheWrite: 0 } } });

async function load(thinking: string, branch: unknown[] = []) {
	return loadExtension("turn-thinking", { pi: { thinking }, ctx: { sessionManager: { getBranch: () => branch } } });
}

describe("turn thinking", () => {
	useEnv({ TURN_THINKING_WAKE_LEVEL: undefined, TURN_THINKING_MAX_CONTEXT: undefined });

	test("a pi-context fork result wake-up lowers the thinking level", async () => {
		const ext = await load("high");
		await ext.fire("before_agent_start", wake("pi-context-results"));
		assert.equal(ext.pi.thinking, "low");
	});

	test("the next user prompt restores the level from before the wake-up", async () => {
		const ext = await load("high");
		await ext.fire("before_agent_start", wake());
		await ext.fire("before_agent_start", user());
		assert.equal(ext.pi.thinking, "high");
	});

	test("think:high does not lower a level above high", async () => {
		const ext = await load("xhigh");
		await ext.fire("before_agent_start", user("think:high please"));
		assert.equal(ext.pi.thinking, "xhigh");
	});

	test("a wake-up keeps the level when the last request's context is above the limit", async () => {
		const ext = await load("high", [reply(50_000)]);
		await ext.fire("before_agent_start", wake());
		assert.equal(ext.pi.thinking, "high");
	});
});
