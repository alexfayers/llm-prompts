import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

type Visible = Record<string, unknown>;
const call = (id: string, name: string, args: Record<string, unknown>) => ({ role: "assistant", content: [{ type: "toolCall", id, name, arguments: args }] });
const result = (id: string, name: string, text: string) => ({ role: "toolResult", toolCallId: id, toolName: name, content: [{ type: "text", text }] });
const readFile = (id: string, text: string, args: Record<string, unknown> = { path: "a.ts" }) => [call(id, "read", args), result(id, "read", text)];

/** A ctx whose projection shows each group of messages as one entry. */
async function load(...groups: Visible[][]) {
	const ext = await loadExtension("already-seen");
	const entries = groups.map((messages, index) => ({ sourceEntry: { id: `e${index}` }, messages }));
	const ctx = ext.makeCtx({ sessionManager: { buildSessionProjection: () => ({ entries }) } as any });
	const run = (event: Record<string, unknown>) => ext.fire("tool_result", { toolCallId: "new", toolName: "read", input: { path: "a.ts" }, content: [{ type: "text", text: "body" }], isError: false, ...event }, ctx);
	return { run };
}

describe("tool_result", () => {
	test("an unchanged repeat read gets a receipt naming the earlier entry", async () => {
		const { run } = await load(readFile("old", "body"));
		const out = await run({});
		assert.deepEqual(out.content, [{ type: "text", text: "unchanged since entry e0, still in context above. If that entry is gone, run the call again" }]);
	});

	test("a read after the file changed, with other arguments, or after the first read left the context gets the full result", async () => {
		const stale = readFile("old", "old body");
		assert.equal(await (await load(stale)).run({}), undefined);
		assert.equal(await (await load(readFile("old", "body", { path: "a.ts", offset: 5 }))).run({}), undefined);
		const folded = [call("old", "read", { path: "a.ts" }), result("old", "read", "[folded]")];
		assert.equal(await (await load(folded)).run({}), undefined);
		assert.equal(await (await load([])).run({}), undefined);
	});
});
