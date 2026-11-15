import assert from "node:assert/strict";
import { test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

useEnv({ PI_CONSULT_MODEL: "strong/expert-1" });

const reply = (text: string, extra: Record<string, unknown> = {}) => ({ role: "assistant", content: [{ type: "text", text }], stopReason: "stop", usage: { cost: { total: 0.5 } }, ...extra });

async function load(result: unknown, model: unknown = { provider: "strong", id: "expert-1" }) {
	const calls: { model: unknown; context: any; options: any }[] = [];
	const modelRegistry = {
		find: (provider: string, id: string) => (provider === "strong" && id === "expert-1" ? model : undefined),
		streamSimple: (modelUsed: unknown, context: unknown, options: unknown) => (calls.push({ model: modelUsed, context, options }), { result: async () => result }),
	};
	const ext = await loadExtension("consult", { ctx: { modelRegistry } as any });
	return { ext, calls };
}

test("the expert gets the question and evidence with no tools and its answer comes back", async () => {
	const { ext, calls } = await load(reply("Use the index."));
	const controller = new AbortController();
	const result = await ext.tools.consult.execute("id", { question: "Why is it slow?", evidence: ["log line", "query"] }, controller.signal, undefined, ext.ctx);
	assert.equal(result.content[0].text, "Use the index.");
	assert.deepEqual(result.details, { model: "strong/expert-1", cost: 0.5 });
	assert.equal(calls.length, 1);
	assert.deepEqual(calls[0].model, { provider: "strong", id: "expert-1" });
	assert.equal(calls[0].context.tools, undefined);
	assert.match(calls[0].context.messages[0].content, /Why is it slow\?[\s\S]*log line[\s\S]*query/);
	assert.equal(calls[0].options.signal, controller.signal);
});
