// Real-model check that a run-end fold is accepted and the cache still covers the prefix before it. Runs only with PI_CONTEXT_INTEGRATION=1, PI_CONTEXT_AGENT_DIR set to a scratch agent directory, PI_CONTEXT_PROVIDER and PI_CONTEXT_MODELS set.
// Env: PI_CONTEXT_PROVIDER (model provider id, required), PI_CONTEXT_MODELS (comma-separated model ids, required), PI_CONTEXT_MIN_CACHE_RATIO (default 0.9)
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
const MIN_RATIO = Number(process.env.PI_CONTEXT_MIN_CACHE_RATIO ?? 0.9);
const facts = (lines: number) => Array.from({ length: lines }, (_, i) => `Fact ${i}: the value of item ${i} is ${(i * 7919) % 10007} and its label is item-${i}-label.`).join("\n");
const rows = (n: number) => Array.from({ length: 240 }, (_, i) => `row ${n}.${i}: value ${(n * 131 + i * 17) % 997}`).join("\n");

useEnv({ CONTEXT_FOLD: "on", CONTEXT_FOLD_PENDING_TOKENS: "100", CONTEXT_FOLD_KEEP_TOKENS: "1500", PI_CONTEXT_CHILD: undefined, AWS_REGION: process.env.AWS_REGION ?? "us-east-1" });

for (const modelId of MODELS)
	test(`after a fold ${modelId} accepts the next run and reads the cached prefix`, { skip: !process.env.PI_CONTEXT_INTEGRATION || !process.env.PI_CONTEXT_PROVIDER || !process.env.PI_CONTEXT_MODELS, timeout: 600_000 }, async () => {
		const agentDir = process.env.PI_CONTEXT_AGENT_DIR;
		assert.ok(agentDir && path.resolve(agentDir) !== path.join(os.homedir(), ".pi", "agent"), "PI_CONTEXT_AGENT_DIR must name a scratch agent directory");
		process.env.PI_CODING_AGENT_DIR = agentDir;
		const modelRuntime = await ModelRuntime.create({ authPath: path.join(agentDir, "auth.json"), modelsPath: path.join(agentDir, "models.json") });
		const lookup = (pi: ExtensionAPI) =>
			pi.registerTool({ name: "lookup", label: "lookup", description: "Returns the rows for n", parameters: Type.Object({ n: Type.Integer() }), async execute(_id, params) { return { content: [{ type: "text", text: rows(params.n) }], details: {} }; } });
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

		await session.prompt(`${facts(500)}\n\nCall lookup with n=1. After its result, think hard about whether the rows are consistent, then call lookup with n=2. After its result, think hard again, then reply with only the word done.`);
		const folds = sessionManager.getEntries().filter((entry: any) => entry.type === "custom" && entry.customType === "context-fold");
		const firstRun = requests.length;
		await session.prompt("Think step by step. Call lookup with n=3, then reply with only the word ok.");
		session.dispose();

		assert.deepEqual(requests.filter((request) => request.stop === "error").map((request) => request.error), []);
		assert.ok(folds.length > 0, "the first run folded nothing");
		assert.ok(requests.length - firstRun >= 2, "the second run made fewer than 2 requests");
		assert.ok(requests[firstRun].cacheRead >= MIN_RATIO * requests[0].total, `cache read ${requests[firstRun].cacheRead} of a ${requests[0].total} token prefix`);
	});
