import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { fauxAssistantMessage, fauxProvider, fauxToolCall, type FauxResponseStep } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, type ExtensionAPI, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import attic from "../../src/llm_prompts/prompts/pi/extensions/attic/index.ts";
import { useEnv } from "./helpers.ts";

const dir = mkdtempSync(join(tmpdir(), "attic-sdk-"));
const manifestFile = join(dir, "attic.json");
useEnv({ PI_ATTIC: manifestFile });

async function start(items: unknown[], extra: (pi: ExtensionAPI) => void, ...responses: FauxResponseStep[]) {
	mkdirSync(join(dir, "skills", "rare-skill"), { recursive: true });
	writeFileSync(join(dir, "skills", "rare-skill", "SKILL.md"), "---\nname: rare-skill\ndescription: A rarely used skill\n---\nRare skill body\n");
	writeFileSync(manifestFile, JSON.stringify({ items }));
	const faux = fauxProvider();
	const modelRuntime = await ModelRuntime.create({ authPath: join(dir, "auth.json"), modelsPath: null, refreshOnCreate: false });
	modelRuntime.registerNativeProvider(faux.provider);
	const rare = (pi: ExtensionAPI) =>
		pi.registerTool({ name: "rare_tool", label: "rare", description: "A rarely used tool", parameters: Type.Object({}), async execute() { return { content: [{ type: "text", text: "rare ran" }], details: {} }; } });
	const resourceLoader = new DefaultResourceLoader({ cwd: dir, agentDir: dir, noExtensions: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [rare, attic, extra] });
	await resourceLoader.reload();
	const { session } = await createAgentSession({ cwd: dir, agentDir: dir, model: faux.getModel(), modelRuntime, resourceLoader, sessionManager: SessionManager.inMemory(dir), settingsManager: SettingsManager.inMemory({}), tools: ["read", "rare_tool", "unlock"] });
	await session.bindExtensions({});
	const requests: any[] = [];
	faux.setResponses(responses.map((step) => (typeof step === "function" ? (context, ...rest) => (requests.push(context), step(context, ...rest)) : step)));
	return { session, requests };
}

const leading = (request: any) => request.messages.find((message: any) => message.role === "system");
const patches = (request: any) => request.messages.filter((message: any) => message.role === "system").slice(1);

test("hidden skills and tools reach the model only as stubs and an unlock appends to the prefix instead of changing it", async () => {
	const { session, requests } = await start(
		[{ kind: "skill", name: "rare-skill", stub: "a rare skill" }, { kind: "tool", name: "rare_tool", stub: "a rare tool" }],
		() => {},
		() => fauxAssistantMessage([fauxToolCall("unlock", { name: "rare-skill" })]),
		() => fauxAssistantMessage([fauxToolCall("unlock", { name: "rare_tool" })]),
		() => fauxAssistantMessage("done"),
		() => fauxAssistantMessage("again"),
	);
	await session.prompt("go");
	await session.prompt("next");
	session.dispose();

	const first = leading(requests[0]);
	assert.deepEqual(Object.keys(first.sections).filter((name) => name === "skills"), []);
	assert.match(first.sections.attic, /- rare-skill: a rare skill\n- rare_tool: a rare tool/);
	assert.deepEqual(first.toolsAdded.map((tool: any) => tool.name), ["read", "unlock"]);
	assert.match(JSON.stringify(requests[1].messages), /Rare skill body/);
	for (const request of requests) assert.deepEqual(leading(request), first);
	assert.deepEqual(patches(requests[1]), []);
	assert.deepEqual(patches(requests[2]).map((patch: any) => patch.toolsAdded.map((tool: any) => tool.name)), [["rare_tool"]]);
});

after(() => rmSync(dir, { recursive: true }));
