import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import consult from "../../src/llm_prompts/prompts/pi/extensions/consult.ts";

const faux = fauxProvider({ models: [{ id: "main" }, { id: "expert" }] });

test("a consult call reaches the expert model with no tools and the answer joins the session without changing the leading prompt", async () => {
	const dir = mkdtempSync(join(tmpdir(), "consult-sdk-"));
	const modelRuntime = await ModelRuntime.create({ authPath: join(dir, "auth.json"), modelsPath: null, refreshOnCreate: false });
	modelRuntime.registerNativeProvider(faux.provider);
	const resourceLoader = new DefaultResourceLoader({ cwd: dir, agentDir: dir, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [consult] });
	await resourceLoader.reload();
	const { session } = await createAgentSession({ cwd: dir, agentDir: dir, model: faux.getModel("main"), modelRuntime, resourceLoader, sessionManager: SessionManager.inMemory(dir), settingsManager: SettingsManager.inMemory({ llmPrompts: { consult: { model: `${faux.getModel("expert")!.provider}/expert` } } } as any), tools: ["consult"] });
	await session.bindExtensions({});
	const requests: any[] = [];
	const seen = (step: (context: any) => ReturnType<typeof fauxAssistantMessage>) => (context: any) => (requests.push(context), step(context));
	faux.setResponses([
		seen(() => fauxAssistantMessage([fauxToolCall("consult", { question: "Which index?", evidence: ["EXPLAIN output"] })])),
		seen(() => fauxAssistantMessage("Use the second index.")),
		seen(() => fauxAssistantMessage("Applied.")),
	]);
	await session.prompt("go");
	session.dispose();
	rmSync(dir, { recursive: true });

	const [first, expertRequest, last] = requests;
	assert.equal(expertRequest.messages.filter((message: any) => message.role === "system").length, 1);
	assert.match(JSON.stringify(expertRequest.messages), /Which index\?[\s\S]*EXPLAIN output/);
	assert.doesNotMatch(JSON.stringify(expertRequest.messages), /"role":"toolResult"/);
	assert.match(JSON.stringify(last.messages), /Use the second index\./);
	assert.deepEqual(last.messages[0], first.messages[0]);
});
