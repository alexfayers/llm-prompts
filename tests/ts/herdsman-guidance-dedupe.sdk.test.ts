import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, type ExtensionAPI, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import guidanceDedupe from "../../src/llm_prompts/prompts/pi/extensions/herdsman-guidance-dedupe.ts";

test("the saved session and the next request hold the stub for a guidance message sent like herdsman sends it", async () => {
	const dir = mkdtempSync(join(tmpdir(), "herdsman-guidance-dedupe-"));
	const faux = fauxProvider();
	const modelRuntime = await ModelRuntime.create({ authPath: join(dir, "auth.json"), modelsPath: null, refreshOnCreate: false });
	modelRuntime.registerNativeProvider(faux.provider);
	const requests: string[] = [];
	const sender = (pi: ExtensionAPI) =>
		pi.registerTool({
			name: "spawn",
			label: "spawn",
			description: "Sends the delegation guidance",
			parameters: Type.Object({}),
			async execute() {
				pi.sendMessage({ customType: "pi-herdsman-delegation-guidance", content: "LONG GUIDANCE", display: false }, { triggerTurn: true, deliverAs: "steer" });
				return { content: [{ type: "text", text: "spawned" }], details: {} };
			},
		});
	const resourceLoader = new DefaultResourceLoader({
		cwd: dir,
		agentDir: dir,
		noExtensions: true,
		noSkills: true,
		noPromptTemplates: true,
		noThemes: true,
		noContextFiles: true,
		extensionFactories: [sender, guidanceDedupe],
	});
	await resourceLoader.reload();
	const sessionManager = SessionManager.inMemory(dir);
	const { session } = await createAgentSession({ cwd: dir, agentDir: dir, model: faux.getModel(), modelRuntime, resourceLoader, sessionManager, settingsManager: SettingsManager.inMemory({}), tools: ["spawn"] });
	await session.bindExtensions({});
	const reply = (text: string) => (context: unknown) => (requests.push(JSON.stringify(context)), fauxAssistantMessage(text));
	faux.setResponses([fauxAssistantMessage([fauxToolCall("spawn", {})]), reply("one"), reply("two")]);

	await session.prompt("go");
	session.dispose();
	rmSync(dir, { recursive: true });

	const saved = sessionManager.getEntries().filter((entry) => entry.type === "custom_message");
	assert.deepEqual(saved.map((entry) => entry.content), ["(delegation reminder omitted)"]);
	assert.ok(requests.length > 0);
	assert.ok(requests.every((request) => request.includes("(delegation reminder omitted)") && !request.includes("LONG GUIDANCE")));
});
