import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

useEnv({ RESULT_CAP_CHARS: "30" });

const text = (value: string) => [{ type: "text", text: value }];
const result = (overrides: Record<string, unknown> = {}) => ({ toolCallId: "t1", toolName: "bash", input: {}, content: text("a".repeat(40) + "b".repeat(20)), isError: false, ...overrides });

describe("tool_result", () => {
	test("caps an over-cap result to head, marker and tail and stores the full text", async () => {
		const ext = await loadExtension("result-cap");
		const out = await ext.fire("tool_result", result());
		assert.equal(out.content[0].text, `${"a".repeat(20)}\n[capped: 60 chars, ref rc-t1; result_fetch({ref, offset?, limit?, pattern?})]\n${"b".repeat(10)}`);
		assert.deepEqual(ext.pi.appended, [["result-cap", { ref: "rc-t1", text: "a".repeat(40) + "b".repeat(20) }]]);
	});

	test("leaves results unchanged that are short, nested, errors, not text, handoff lines or from exempt tools", async () => {
		const ext = await loadExtension("result-cap");
		const long = "x".repeat(100);
		const cases = [
			result({ content: text("short") }),
			result({ parentToolCallId: "p" }),
			result({ isError: true }),
			result({ content: [...text(long), { type: "image", data: "", mimeType: "image/png" }] }),
			result({ content: text(`${long}\nASK: which one?`) }),
			result({ content: text(`${long}\nDENIED: "no"`) }),
			...["read", "edit", "write", "result_fetch", "checkpoint", "ask_user", "asks"].map((toolName) => result({ toolName })),
		];
		for (const event of cases) assert.equal(await ext.fire("tool_result", event), undefined);
		assert.deepEqual(ext.pi.appended, []);
	});
});

test("keeps the full result when storing it fails", async () => {
	const ext = await loadExtension("result-cap");
	ext.pi.appendEntry = () => {
		throw new Error("disk full");
	};
	assert.equal(await ext.fire("tool_result", result()), undefined);
});

describe("result_fetch", () => {
	const lines = Array.from({ length: 10 }, (_, i) => `line ${i} ${i % 3 ? "plain" : "match"}`).join("\n");

	async function capped() {
		const first = await loadExtension("result-cap");
		await first.fire("tool_result", result({ content: text(lines) }));
		const fresh = await loadExtension("result-cap");
		const branch = first.pi.appended.map(([customType, data]) => ({ type: "custom", customType, data }));
		const ctx = fresh.makeCtx({ sessionManager: { getBranch: () => branch } });
		return (params: object) => fresh.callTool("result_fetch", params, ctx);
	}

	test("returns the stored text from a fresh load, by offset and limit or by matching lines", async () => {
		const fetch = await capped();
		assert.equal((await fetch({ ref: "rc-t1", limit: 10000 })).content[0].text, lines);
		assert.equal((await fetch({ ref: "rc-t1", offset: 7, limit: 6 })).content[0].text, lines.slice(7, 13) + "\n[more: offset 13]");
		assert.equal((await fetch({ ref: "rc-t1", pattern: "match", limit: 10000 })).content[0].text, "0: line 0 match\n3: line 3 match\n6: line 6 match\n9: line 9 match");
	});

	test("reports an unknown ref and an invalid pattern as errors", async () => {
		const fetch = await capped();
		assert.equal((await fetch({ ref: "rc-nope" })).isError, true);
		assert.equal((await fetch({ ref: "rc-t1", pattern: "(" })).isError, true);
	});
});
