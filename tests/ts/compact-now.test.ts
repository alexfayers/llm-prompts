import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

describe("compact_now", () => {
	test("compacts only after the turn settles, then continues", async () => {
		const compacts: string[] = [];
		const ext = await loadExtension("compact-now", {
			ctx: { compact: (options: any) => (compacts.push(options.customInstructions), options.onComplete()) },
		});
		const result = await ext.callTool("compact_now", { instructions: "summary" });
		assert.equal(result.terminate, true);
		assert.deepEqual(compacts, []);
		await ext.fire("agent_settled", { aborted: false });
		await ext.fire("agent_settled", { aborted: false });
		assert.deepEqual(compacts, ["summary"]);
		assert.equal(ext.pi.sent.length, 1);
	});
});
