// Real-model check that a run-end fold is accepted and the cache still covers the prefix before it. Runs only with PI_CONTEXT_INTEGRATION=1, PI_CONTEXT_AGENT_DIR set to a scratch agent directory, PI_CONTEXT_PROVIDER and PI_CONTEXT_MODELS set.
// Env: PI_CONTEXT_PROVIDER (model provider id, required), PI_CONTEXT_MODELS (comma-separated model ids, required), PI_CONTEXT_MIN_CACHE_RATIO (default 0.9). The idle test waits for the real five minute cache to expire.
import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { createAgentSession, DefaultResourceLoader, type ExtensionAPI, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import contextFold from "../../src/llm_prompts/prompts/pi/extensions/context-fold.ts";
import { useEnv } from "./helpers.ts";

const PROVIDER = process.env.PI_CONTEXT_PROVIDER ?? "provider";
const MODELS = process.env.PI_CONTEXT_MODELS?.split(",").map((model) => model.trim()).filter(Boolean) ?? ["model-a", "model-b"];
const CACHE_EXPIRY_MS = 5 * 60_000 + 15_000;
const MIN_RATIO = Number(process.env.PI_CONTEXT_MIN_CACHE_RATIO ?? 0.9);
const facts = (lines: number) => Array.from({ length: lines }, (_, i) => `Fact ${i}: the value of item ${i} is ${(i * 7919) % 10007} and its label is item-${i}-label.`).join("\n");
const rows = (n: number) => Array.from({ length: 240 }, (_, i) => `row ${n}.${i}: value ${(n * 131 + i * 17) % 997}`).join("\n");

useEnv({ CONTEXT_FOLD: "on", CONTEXT_FOLD_PENDING_TOKENS: "100", CONTEXT_FOLD_KEEP_TOKENS: "1500", PI_CONTEXT_CHILD: undefined, CONTEXT_FOLD_IDLE: undefined, CONTEXT_FOLD_IDLE_MIN_TOKENS: "100", PI_CACHE_RETENTION: undefined, AWS_REGION: process.env.AWS_REGION ?? "us-east-1" });

const FIRST_PROMPT = `${facts(500)}\n\nCall lookup with n=1. After its result, think hard about whether the rows are consistent, then call lookup with n=2. After its result, think hard again, then reply with only the word done.`;

async function open(modelId: string) {
	const agentDir = process.env.PI_CONTEXT_AGENT_DIR;
	assert.ok(agentDir && path.resolve(agentDir) !== path.join(os.homedir(), ".pi", "agent"), "PI_CONTEXT_AGENT_DIR must name a scratch agent directory");
	process.env.PI_CODING_AGENT_DIR = agentDir;
	const modelRuntime = await ModelRuntime.create({ authPath: path.join(agentDir, "auth.json"), modelsPath: path.join(agentDir, "models.json") });
	const state = { rejectNext: false };
	const lookup = (pi: ExtensionAPI) => {
		pi.registerTool({ name: "lookup", label: "lookup", description: "Returns the rows for n", parameters: Type.Object({ n: Type.Integer() }), async execute(_id, params) { return { content: [{ type: "text", text: rows(params.n) }], details: {} }; } });
		pi.on("before_provider_request", (event) => (state.rejectNext ? { ...(event.payload as object), messages: [] } : undefined));
	};
	const resourceLoader = new DefaultResourceLoader({ cwd: os.tmpdir(), agentDir, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [lookup, contextFold] });
	await resourceLoader.reload();
	const sessionManager = SessionManager.inMemory(os.tmpdir());
	const { session } = await createAgentSession({ cwd: os.tmpdir(), agentDir, modelRuntime, thinkingLevel: "high", resourceLoader, sessionManager, settingsManager: SettingsManager.inMemory({ defaultProvider: PROVIDER, defaultModel: modelId } as any), tools: ["lookup"] });
	const requests: { cacheRead: number; total: number; stop: string; error?: string }[] = [];
	session.subscribe((event) => {
		if (event.type !== "message_end" || event.message.role !== "assistant") return;
		const { usage, stopReason, errorMessage } = event.message;
		requests.push({ cacheRead: usage.cacheRead, total: usage.input + usage.cacheRead + usage.cacheWrite, stop: stopReason, error: errorMessage });
	});
	await session.bindExtensions({});
	const model = modelRuntime.getModel(PROVIDER, modelId);
	assert.ok(model, `model ${modelId} missing`);
	await session.setModel(model);
	const records = () => sessionManager.getEntries().filter((entry: any) => entry.type === "custom" && entry.customType === "context-fold").map((entry: any) => entry.data.trigger);
	return { session, state, requests, records };
}

const skip = !process.env.PI_CONTEXT_INTEGRATION || !process.env.PI_CONTEXT_PROVIDER || !process.env.PI_CONTEXT_MODELS;

for (const modelId of MODELS) {
	test(`after a fold ${modelId} accepts the next run and reads the cached prefix`, { skip, timeout: 600_000 }, async () => {
		const { session, requests, records } = await open(modelId);
		await session.prompt(FIRST_PROMPT);
		const firstRun = requests.length;
		await session.prompt("Think step by step. Call lookup with n=3, then reply with only the word ok.");
		session.dispose();

		assert.deepEqual(requests.filter((request) => request.stop === "error").map((request) => request.error), []);
		assert.equal(records()[0], "run-end");
		assert.ok(!records().includes("revert"));
		assert.ok(requests.length - firstRun >= 2, "the second run made fewer than 2 requests");
		assert.ok(requests[firstRun].cacheRead >= MIN_RATIO * requests[0].total, `cache read ${requests[firstRun].cacheRead} of a ${requests[0].total} token prefix`);
	});

	test(`an aborted message is pruned and ${modelId} accepts the next run`, { skip, timeout: 600_000 }, async () => {
		const { session, requests, records } = await open(modelId);
		let streamed = 0;
		const aborts: Promise<void>[] = [];
		session.subscribe((event) => {
			if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta" && !aborts.length && (streamed += event.assistantMessageEvent.delta.length) > 1500) aborts.push(session.abort());
		});
		await session.prompt("Write a 600 word story about a lighthouse.");
		await Promise.all(aborts);
		await session.prompt(FIRST_PROMPT);
		await session.prompt("Reply with only the word ok.");
		const entries = session.sessionManager.getEntries() as any[];
		session.dispose();

		const abortedId = entries.find((entry) => entry.type === "message" && entry.message.role === "assistant" && entry.message.stopReason === "aborted")?.id;
		assert.ok(abortedId, "no aborted message was recorded");
		assert.deepEqual(requests.filter((request) => request.stop === "error").map((request) => request.error), []);
		assert.ok(records().includes("run-end"));
		assert.ok(entries.some((entry) => entry.type === "custom" && entry.customType === "context-fold" && entry.data.targets.includes(abortedId)));
		assert.notEqual(requests.at(-1)?.stop, "error");
	});

	test(`the idle fold of the first request after the cache expired is accepted by ${modelId} and the next request reads the cache of it`, { skip, timeout: 900_000 }, async () => {
		process.env.CONTEXT_FOLD_PENDING_TOKENS = "1000000";
		const { session, requests, records } = await open(modelId);
		await session.prompt(FIRST_PROMPT);
		const firstRun = requests.length;
		await new Promise((resolve) => setTimeout(resolve, CACHE_EXPIRY_MS));
		await session.prompt("Think step by step. Call lookup with n=3, then reply with only the word ok.");
		session.dispose();

		assert.deepEqual(requests.filter((request) => request.stop === "error").map((request) => request.error), []);
		assert.deepEqual(records(), ["idle"]);
		assert.ok(requests.length - firstRun >= 2, "the second run made fewer than 2 requests");
		assert.ok(requests[firstRun].total < requests[firstRun - 1].total, `request 1 sent ${requests[firstRun].total} tokens, the unfolded context had ${requests[firstRun - 1].total}`);
		assert.ok(requests[firstRun + 1].cacheRead >= MIN_RATIO * requests[firstRun].total, `cache read ${requests[firstRun + 1].cacheRead} of a ${requests[firstRun].total} token prefix`);
	});

	test(`after a rejected request ${modelId} gets the folded entries back and reads the cached prefix`, { skip, timeout: 600_000 }, async () => {
		const { session, state, requests, records } = await open(modelId);
		await session.prompt(FIRST_PROMPT);
		state.rejectNext = true;
		await session.prompt("Reply with only the word ok.");
		state.rejectNext = false;
		const rejected = requests.length;
		await session.prompt("Reply with only the word ok.");
		session.dispose();

		assert.equal(requests[rejected - 1].stop, "error");
		assert.deepEqual(records(), ["run-end", "revert"]);
		assert.notEqual(requests[rejected].stop, "error");
		assert.ok(requests[rejected].cacheRead >= MIN_RATIO * requests[0].total, `cache read ${requests[rejected].cacheRead} of a ${requests[0].total} token prefix`);
	});
}
