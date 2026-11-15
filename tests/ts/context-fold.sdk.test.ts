import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fauxAssistantMessage, fauxProvider, fauxText, fauxThinking, fauxToolCall } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, type ExtensionAPI, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import contextFold from "../../src/llm_prompts/prompts/pi/extensions/context-fold.ts";
import { useEnv } from "./helpers.ts";

useEnv({ CONTEXT_FOLD: "on", CONTEXT_FOLD_PENDING_TOKENS: "100", CONTEXT_FOLD_KEEP_TOKENS: "1200", PI_CONTEXT_CHILD: undefined });

const BIG = "z".repeat(4000);

test("pi accepts a run-end fold and the next request holds the stub, no later thinking and every call with its result", async () => {
	const dir = mkdtempSync(join(tmpdir(), "context-fold-"));
	const faux = fauxProvider();
	const modelRuntime = await ModelRuntime.create({ authPath: join(dir, "auth.json"), modelsPath: null, refreshOnCreate: false });
	modelRuntime.registerNativeProvider(faux.provider);
	const big = (pi: ExtensionAPI) =>
		pi.registerTool({ name: "big", label: "big", description: "Returns a long result", parameters: Type.Object({}), async execute() { return { content: [{ type: "text", text: BIG }], details: {} }; } });
	const resourceLoader = new DefaultResourceLoader({ cwd: dir, agentDir: dir, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [big, contextFold] });
	await resourceLoader.reload();
	const sessionManager = SessionManager.inMemory(dir);
	const { session } = await createAgentSession({ cwd: dir, agentDir: dir, model: faux.getModel(), modelRuntime, resourceLoader, sessionManager, settingsManager: SettingsManager.inMemory({}), tools: ["big"] });
	await session.bindExtensions({});
	const requests: any[] = [];
	faux.setResponses([
		fauxAssistantMessage([fauxThinking("T1"), fauxToolCall("big", {})]),
		fauxAssistantMessage([fauxThinking("T2"), fauxToolCall("big", {})]),
		fauxAssistantMessage([fauxThinking("T3"), fauxText("done")]),
		(context: unknown) => (requests.push(context), fauxAssistantMessage("again")),
	]);

	await session.prompt("go");
	await session.prompt("again?");
	session.dispose();
	rmSync(dir, { recursive: true });

	const entries = sessionManager.getEntries();
	assert.deepEqual(entries.filter((entry) => entry.type === "custom" && entry.customType === "context-fold").map((entry: any) => entry.data.mode), ["on"]);
	const messages: any[] = requests.at(-1).messages;
	const sent = JSON.stringify(messages);
	assert.ok(/\[folded: big \{\} -> 4000 chars; result_fetch\(\{ref:\\"fold-[^"\\]+\\"\}\) resends it\]/.test(sent));
	assert.equal(sent.split(BIG).length - 1, 1);
	assert.ok(sent.includes("T1") && !sent.includes("T2") && !sent.includes("T3"));
	const calls = messages.flatMap((message) => (message.role === "assistant" ? message.content.filter((block: any) => block.type === "toolCall").map((block: any) => block.id) : []));
	assert.deepEqual(calls.sort(), messages.filter((message) => message.role === "toolResult").map((message) => message.toolCallId).sort());
});
