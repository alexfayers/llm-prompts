import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const usage = (cacheRead: number, cacheWrite: number) => ({ input: 10, cacheRead, cacheWrite, cost: { input: 0, cacheRead: cacheRead * 0.3e-6, cacheWrite: cacheWrite * 3.75e-6 } });
const assistant = (cacheRead: number, cacheWrite: number, timestamp: number) => ({ role: "assistant", usage: usage(cacheRead, cacheWrite), timestamp });
const result = { toolCallId: "c", toolName: "bash", input: {}, content: [{ type: "text", text: "out" }], isError: false };

describe("cache miss notice", () => {
	useEnv({ PI_CACHE_RETENTION: undefined });

	test("tells the model once, on the next tool result, about a miss after a thinking level change", async () => {
		const branch: unknown[] = [{ type: "message", message: assistant(100_000, 40_000, 0) }, { type: "thinking_level_change", thinkingLevel: "high" }];
		const ext = await loadExtension("cache-miss-notice");
		ext.ctx.sessionManager.getBranch = () => branch as never;
		await ext.fire("message_end", { message: assistant(1_000, 140_000, 60_000) });

		const out = await ext.fire("tool_result", result);
		assert.equal(out.content[0].text, "out");
		assert.equal(out.content[1].text, "[cache] miss: 139k re-written (~$0.48) after a thinking level change to high. If an extension or your own action caused it, fix that.");
		assert.equal(await ext.fire("tool_result", result), undefined);
	});

	test("drops a miss no tool result took before the turn ends", async () => {
		const branch: unknown[] = [{ type: "message", message: assistant(100_000, 40_000, 0) }, { type: "thinking_level_change", thinkingLevel: "high" }];
		const ext = await loadExtension("cache-miss-notice");
		ext.ctx.sessionManager.getBranch = () => branch as never;
		await ext.fire("message_end", { message: assistant(1_000, 140_000, 60_000) });
		await ext.fire("turn_end", {});
		assert.equal(await ext.fire("tool_result", result), undefined);
	});
});
