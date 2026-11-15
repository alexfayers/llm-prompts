import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fauxAssistantMessage, fauxProvider } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, type ExtensionAPI, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import turnThinking from "../../src/llm_prompts/prompts/pi/extensions/turn-thinking.ts";

test("a Herdsman wake-up turn is requested at the wake level and the next user prompt at the restored level", async () => {
	const dir = mkdtempSync(join(tmpdir(), "turn-thinking-"));
	const faux = fauxProvider({ models: [{ id: "reasoner", reasoning: true }] });
	const modelRuntime = await ModelRuntime.create({ authPath: join(dir, "auth.json"), modelsPath: null, refreshOnCreate: false });
	modelRuntime.registerNativeProvider(faux.provider);
	const waker = (pi: ExtensionAPI) =>
		pi.registerCommand("wake", {
			description: "Sends a Herdsman result message that starts a turn",
			handler: async () => pi.sendMessage({ customType: "pi-herdsman-agent-result", content: "OUTCOME done", display: false }, { triggerTurn: true }),
		});
	const resourceLoader = new DefaultResourceLoader({ cwd: dir, agentDir: dir, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [waker, turnThinking] });
	await resourceLoader.reload();
	const { session } = await createAgentSession({
		cwd: dir,
		agentDir: dir,
		model: faux.getModel("reasoner"),
		thinkingLevel: "high",
		modelRuntime,
		resourceLoader,
		sessionManager: SessionManager.inMemory(dir),
		settingsManager: SettingsManager.inMemory({}),
		tools: [],
	});
	await session.bindExtensions({});
	const reasoning: unknown[] = [];
	const reply = (_context: unknown, options?: { reasoning?: unknown }) => (reasoning.push(options?.reasoning), fauxAssistantMessage("ok"));
	faux.setResponses([reply, reply]);

	await session.prompt("/wake");
	await session.waitForIdle();
	await session.prompt("next");
	session.dispose();
	rmSync(dir, { recursive: true });

	assert.deepEqual(reasoning, ["low", "high"]);
});
