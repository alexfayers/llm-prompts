import assert from "node:assert/strict";
import { join } from "node:path";
import { describe, test } from "node:test";
import { loadExtension, useMemoryFs } from "./helpers.ts";

const VARIANTS = { worker: { sonnet: { model: "prov/sonnet", efforts: { low: "low", high: "high" } } } };
const LEAD = { provider: "prov", id: "lead" };

const memory = useMemoryFs();
const schema = (definitions: string[]) => ({ properties: { definition: { enum: definitions } } });

async function load(definitions: string[], refuse: string[] = []) {
	const agentDir = join(memory.root, "agent");
	memory.write(join(agentDir, "agent-role-variants.json"), JSON.stringify(VARIANTS));
	const tool = { name: "delegate_agent", parameters: schema(definitions) };
	const ext = await loadExtension("role-switch", { agentDir, pi: { model: LEAD, thinking: "medium", allTools: [tool] } });
	ext.pi.setModel = async (model: any) => (refuse.includes(model.id) || (ext.pi.model = model), true);
	const ctx = ext.makeCtx({ modelRegistry: { find: (provider: string, id: string) => ({ provider, id }) } });
	Object.defineProperty(ctx, "model", { get: () => ext.pi.model });
	await ext.fire("session_start", {}, ctx);
	return { ext, ctx, tool };
}

async function delegate(definition: string, definitions: string[], refuse: string[] = []) {
	const { ext, ctx } = await load(definitions, refuse);
	const input = { definition };
	const event = { toolName: "delegate_agent", input };
	const result = await ext.fire("tool_call", event, ctx);
	const state = () => [(ext.pi.model as any).id, ext.pi.thinking];
	const during = state();
	await ext.fire("tool_execution_end", event, ctx);
	return { result, input, during, after: state() };
}

test("session start adds variant names to the enum", async () => {
	const { tool } = await load(["Explore", "worker"]);
	assert.deepEqual(tool.parameters.properties.definition.enum, ["Explore", "worker", "worker@sonnet:low", "worker@sonnet:high"]);
});

test("delegation switches the model then restores", async () => {
	const { result, input, during, after } = await delegate("worker@sonnet:high", ["worker"]);
	assert.equal(result, undefined);
	assert.equal(input.definition, "worker");
	assert.deepEqual(during, ["sonnet", "high"]);
	assert.deepEqual(after, ["lead", "medium"]);
});

describe("a failed switch or plain role is blocked", () => {
	for (const [name, refuse] of [["worker@sonnet:low", ["sonnet"]], ["worker", []]] as [string, string[]][]) {
		test(name, async () => {
			const { result, after } = await delegate(name, ["worker"], refuse);
			assert.equal(result.block, true);
			assert.deepEqual(after, ["lead", "medium"]);
		});
	}
});

describe("unlisted names are left alone", () => {
	for (const [name, definitions] of [
		["worker@sonnet:high", ["Explore"]],
	] as [string, string[]][]) {
		test(`${name} with ${definitions}`, async () => {
			const { result, input, during } = await delegate(name, definitions);
			assert.equal(result, undefined);
			assert.equal(input.definition, name);
			assert.deepEqual(during, ["lead", "medium"]);
		});
	}
});
