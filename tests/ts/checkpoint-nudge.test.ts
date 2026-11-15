import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const result = (tokens: number, toolName = "bash") => ({ toolCallId: "c", toolName, input: {}, content: [{ type: "text", text: "x".repeat(tokens * 4) }], isError: false });
const nudged = (out: any) => out?.content?.some((block: { text?: string }) => block.text?.startsWith("[checkpoint]")) ?? false;

describe("checkpoint nudge", () => {
	useEnv({ PI_CONTEXT_CHILD: undefined, PI_HERDSMAN_MAILBOX: undefined, CHECKPOINT_NUDGE_TOKENS: "1000" });

	test("nudges each time another threshold of result tokens builds up since the user message, keeps the result, and resets on a checkpoint call or a new run", async () => {
		const ext = await loadExtension("checkpoint-nudge");
		await ext.fire("agent_start");
		const outs = [];
		for (let i = 0; i < 8; i++) outs.push(await ext.fire("tool_result", result(400)));
		assert.deepEqual(outs.map(nudged), [false, false, true, false, false, true, false, false]);
		assert.equal(outs[2].content[0].text.length, 1600);
		assert.match(outs[2].content[1].text, /3 calls, ~1K tokens since the last user message.*checkpoint rewind to the call before it, or to a mark set before it, with a summary/);

		await ext.fire("tool_result", result(0, "checkpoint"));
		assert.equal(nudged(await ext.fire("tool_result", result(900))), false);
		await ext.fire("agent_start");
		assert.equal(nudged(await ext.fire("tool_result", result(900))), false);
		assert.equal(nudged(await ext.fire("tool_result", result(100))), true);
	});
});
