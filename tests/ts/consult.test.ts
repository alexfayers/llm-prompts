import assert from "node:assert/strict";
import { test } from "node:test";
import { loadExtension } from "./helpers.ts";

const SESSION_MODEL = { provider: "main", id: "session-1", reasoning: true, thinkingLevelMap: { xhigh: "xhigh", max: "max" } };
const EXPERT_MODEL = { provider: "strong", id: "expert-1", reasoning: false };
const reply = (text: string, usage: unknown = { cost: { total: 0.5 } }) => ({ role: "assistant", content: [{ type: "text", text }], stopReason: "stop", usage });

async function load(settings: unknown = {}, usage?: unknown) {
	const calls: { model: unknown; context: any; options: any }[] = [];
	const modelRegistry = {
		find: (provider: string, id: string) => (provider === "strong" && id === "expert-1" ? EXPERT_MODEL : undefined),
		streamSimple: (model: unknown, context: unknown, options: unknown) => (calls.push({ model, context, options }), { result: async () => reply("Use the index.", usage) }),
	};
	const ext = await loadExtension("consult", { pi: { getSettings: () => settings } as any, ctx: { model: SESSION_MODEL, modelRegistry } as any });
	const ask = (signal = new AbortController().signal) => ext.tools.consult.execute("id", { question: "Why is it slow?", evidence: ["log line", "query"] }, signal, undefined, ext.ctx);
	return { ask, calls };
}

test("by default the session's model answers in a fresh context with no tools at its highest thinking level", async () => {
	const { ask, calls } = await load();
	const controller = new AbortController();
	const result = await ask(controller.signal);
	assert.equal(result.content[0].text, "Use the index.");
	assert.deepEqual(result.details, { model: "main/session-1", reasoning: "max", cost: 0.5 });
	assert.equal(calls.length, 1);
	assert.equal(calls[0].model, SESSION_MODEL);
	assert.equal(calls[0].context.tools, undefined);
	assert.equal(calls[0].context.messages.length, 1);
	assert.match(calls[0].context.messages[0].content, /Why is it slow\?[\s\S]*log line[\s\S]*query/);
	assert.equal(calls[0].options.signal, controller.signal);
	assert.equal(calls[0].options.reasoning, "max");
});

test("llmPrompts.consult.model picks the expert, and a model without reasoning gets no thinking level", async () => {
	const { ask, calls } = await load({ llmPrompts: { consult: { model: "strong/expert-1" } } });
	const result = await ask();
	assert.equal(calls[0].model, EXPERT_MODEL);
	assert.equal(calls[0].options.reasoning, undefined);
	assert.equal(result.details.model, "strong/expert-1");
});

test("a configured model that is not available fails the call", async () => {
	const { ask } = await load({ llmPrompts: { consult: { model: "strong/missing" } } });
	await assert.rejects(ask(), /strong\/missing is not available/);
});

test("an answer without pricing data reports zero cost", async () => {
	const { ask } = await load({}, {});
	const result = await ask();
	assert.equal(result.content[0].text, "Use the index.");
	assert.equal(result.details.cost, 0);
});
