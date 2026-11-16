import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, type ExtensionAPI, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { Recorder, registerRecorder } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/ghost/recorder.ts";

test("a real run records its steps in order, with the calls a tool made, and a later failing run replaces it", async () => {
	const dir = mkdtempSync(join(tmpdir(), "ghost-recorder-"));
	const faux = fauxProvider();
	const modelRuntime = await ModelRuntime.create({ authPath: join(dir, "auth.json"), modelsPath: null, refreshOnCreate: false });
	modelRuntime.registerNativeProvider(faux.provider);
	const recorder = new Recorder();
	const text = (value: string) => ({ content: [{ type: "text" as const, text: value }], details: {} });
	const extension = (pi: ExtensionAPI) => {
		registerRecorder(pi, recorder);
		pi.registerTool({ name: "alpha", label: "alpha", description: "Returns a", parameters: Type.Object({ n: Type.Optional(Type.Number()) }), execute: async () => text("a") });
		pi.registerTool({ name: "beta", label: "beta", description: "Calls alpha", parameters: Type.Object({}), execute: async (_id, _params, _signal, _update, ctx) => (await ctx.executeTool("alpha", { n: 1 }), text("b")) });
		pi.registerTool({ name: "boom", label: "boom", description: "Throws", parameters: Type.Object({}), execute: async () => Promise.reject(new Error("no")) });
	};
	const resourceLoader = new DefaultResourceLoader({ cwd: dir, agentDir: dir, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [extension] });
	await resourceLoader.reload();
	const { session } = await createAgentSession({ cwd: dir, agentDir: dir, model: faux.getModel(), modelRuntime, resourceLoader, sessionManager: SessionManager.inMemory(dir), settingsManager: SettingsManager.inMemory({}), tools: ["alpha", "beta", "boom"] });
	await session.bindExtensions({});

	faux.setResponses([fauxAssistantMessage([fauxToolCall("alpha", { n: 7 }), fauxToolCall("beta", {})]), fauxAssistantMessage("done")]);
	await session.prompt("go");
	const first = recorder.last()!;
	assert.deepEqual(first.steps.map((step) => [step.tool, step.args, step.nested]), [["alpha", { n: 7 }, undefined], ["beta", {}, [{ tool: "alpha", isError: false }]]]);
	assert.deepEqual(first.outputs, ["a", "b"]);
	assert.equal(first.clean, true);

	faux.setResponses([fauxAssistantMessage([fauxToolCall("boom", {})]), fauxAssistantMessage("failed")]);
	await session.prompt("again");
	assert.deepEqual(recorder.last()!.steps.map((step) => step.tool), ["boom"]);
	assert.equal(recorder.last()!.clean, false);

	session.dispose();
	rmSync(dir, { recursive: true });
});
