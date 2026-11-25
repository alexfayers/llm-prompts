import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { registerHooks } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, mock, test } from "node:test";
import { fauxAssistantMessage, fauxProvider, fauxText, fauxThinking, fauxToolCall, type FauxResponseStep } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, type ExtensionAPI, type ExtensionFactory, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import contextFold from "../../src/llm_prompts/prompts/pi/extensions/context-fold.ts";
import towerDoSlim from "../../src/llm_prompts/prompts/pi/extensions/tower-do-slim.ts";
import { useEnv } from "./helpers.ts";

const AGENT_DIR = "/agent";
const BOARD = "TowerDo shared board \u2014 you are main (revision 1; 1 task(s), 1 open, 0 blocked, 0 unread message(s) for you).\n- [pending] a: subject a";
const towerUrl = (file: string) => pathToFileURL(join(AGENT_DIR, "npm", "node_modules", "tower-do", file)).href;
const towerSources: Record<string, string> = {
	[towerUrl("state.ts")]: "export const MAX_TOWER_DO_OPEN_TASKS = 50; export const formatTakeoverWindow = () => '6h'; export const TASK_KEY_PATTERN = /^[a-z0-9][a-z0-9._-]{0,39}$/;",
	[towerUrl("index.ts")]: `export default function (pi) {
		pi.on("context", (event) => ({ messages: [...event.messages, { role: "custom", customType: "pi-tower-do-reminder", content: ${JSON.stringify(BOARD)}, display: false, timestamp: Date.now() }] }));
	}`,
};
const hooks = registerHooks({
	resolve: (specifier, context, next) => (specifier in towerSources ? { url: specifier, format: "module", shortCircuit: true } : next(specifier, context)),
	load: (url, context, next) => (url in towerSources ? { format: "module", source: towerSources[url], shortCircuit: true } : next(url, context)),
});
after(() => hooks.deregister());

useEnv({ PI_CODING_AGENT_DIR: AGENT_DIR, CONTEXT_FOLD: "run-end", CONTEXT_FOLD_PENDING_TOKENS: "100", CONTEXT_FOLD_KEEP_TOKENS: "1200", PI_CONTEXT_CHILD: undefined, CONTEXT_FOLD_IDLE: undefined, CONTEXT_FOLD_IDLE_MIN_TOKENS: "100", PI_CACHE_RETENTION: undefined });

const BIG = "z".repeat(4000);

async function start(responses: FauxResponseStep[], extensions: ExtensionFactory[] = []) {
	const dir = mkdtempSync(join(tmpdir(), "context-fold-"));
	const faux = fauxProvider();
	const modelRuntime = await ModelRuntime.create({ authPath: join(dir, "auth.json"), modelsPath: null, refreshOnCreate: false });
	modelRuntime.registerNativeProvider(faux.provider);
	const big = (pi: ExtensionAPI) =>
		pi.registerTool({ name: "big", label: "big", description: "Returns a long result", parameters: Type.Object({}), async execute() { return { content: [{ type: "text", text: BIG }], details: {} }; } });
	const resourceLoader = new DefaultResourceLoader({ cwd: dir, agentDir: dir, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [big, ...extensions, contextFold] });
	await resourceLoader.reload();
	const sessionManager = SessionManager.inMemory(dir);
	const { session } = await createAgentSession({ cwd: dir, agentDir: dir, model: faux.getModel(), modelRuntime, resourceLoader, sessionManager, settingsManager: SettingsManager.inMemory({}), tools: ["big"] });
	await session.bindExtensions({});
	const requests: any[] = [];
	faux.setResponses(responses.map((step) => (context, ...rest) => (requests.push(context), typeof step === "function" ? step(context, ...rest) : step)));
	return {
		session,
		sessionManager,
		requests,
		finish() {
			session.dispose();
			rmSync(dir, { recursive: true });
		},
	};
}

const TWO_BIG_CALLS = [
	fauxAssistantMessage([fauxThinking("T1"), fauxToolCall("big", {})]),
	fauxAssistantMessage([fauxThinking("T2"), fauxToolCall("big", {})]),
	fauxAssistantMessage([fauxThinking("T3"), fauxText("done")]),
];

test("pi accepts a run-end fold and the next request holds the stub, no later thinking and every call with its result", async () => {
	const { session, sessionManager, requests, finish } = await start([...TWO_BIG_CALLS, () => fauxAssistantMessage("again")]);
	await session.prompt("go");
	await session.prompt("again?");
	finish();

	const entries = sessionManager.getEntries();
	assert.deepEqual(entries.filter((entry) => entry.type === "custom" && entry.customType === "context-fold").map((entry: any) => entry.data.mode), ["run-end"]);
	const messages: any[] = requests.at(-1).messages;
	const sent = JSON.stringify(messages);
	assert.ok(/\[folded: big \{\} -> 4000 chars; result_fetch\(\{ref:\\"fold-[^"\\]+\\"\}\) resends it, transcript\(\) shows the steps around it\]/.test(sent));
	assert.equal(sent.split(BIG).length - 1, 1);
	const thinking = messages.flatMap((message) => (message.role === "assistant" ? message.content.filter((block: any) => block.type === "thinking").map((block: any) => block.thinking) : []));
	assert.deepEqual(thinking, ["T1"]);
	const calls = messages.flatMap((message) => (message.role === "assistant" ? message.content.filter((block: any) => block.type === "toolCall").map((block: any) => block.id) : []));
	assert.deepEqual(calls.sort(), messages.filter((message) => message.role === "toolResult").map((message) => message.toolCallId).sort());
});

test("pi accepts the undo of a fold after a rejected request and the request after it holds the full results again", async () => {
	const { session, sessionManager, requests, finish } = await start([
		...TWO_BIG_CALLS,
		() => fauxAssistantMessage("", { stopReason: "error", errorMessage: "400 thinking block rejected" }),
		() => fauxAssistantMessage("third"),
	]);
	await session.prompt("go");
	await session.prompt("again?");
	await session.prompt("once more?");
	finish();

	const records = sessionManager.getEntries().filter((entry: any) => entry.type === "custom" && entry.customType === "context-fold").map((entry: any) => entry.data.trigger);
	assert.deepEqual(records, ["run-end", "revert"]);
	const sent = JSON.stringify(requests.at(-1).messages);
	assert.equal(sent.split(BIG).length - 1, 2);
	assert.ok(!sent.includes("[folded:") && sent.includes("T2"));
});

const CACHE_EXPIRY_MS = 10 * 60_000;

function idleStart(responses: FauxResponseStep[], extensions: ExtensionFactory[] = []) {
	process.env.CONTEXT_FOLD_PENDING_TOKENS = "1000000";
	let skew = 0;
	const now = Date.now;
	mock.method(Date, "now", () => now() + skew);
	return start([...TWO_BIG_CALLS, ...responses], extensions).then((started) => ({ ...started, expireCache: () => void (skew += CACHE_EXPIRY_MS), finish: () => (mock.restoreAll(), started.finish()) }));
}

test("a rejected idle fold is not saved and folding stops", async () => {
	const { session, sessionManager, requests, expireCache, finish } = await idleStart([() => fauxAssistantMessage("", { stopReason: "error", errorMessage: "400 thinking block rejected" }), () => fauxAssistantMessage("third")]);
	await session.prompt("go");
	expireCache();
	await session.prompt("again?");
	expireCache();
	await session.prompt("once more?");
	finish();

	assert.equal(sessionManager.getEntries().filter((entry: any) => entry.type === "custom" && entry.customType === "context-fold").length, 0);
	assert.equal(JSON.stringify(requests.at(-1).messages).split(BIG).length - 1, 2);
});

test("a board note folded by an idle fold is not restated for the same revision", async () => {
	const { session, sessionManager, requests, expireCache, finish } = await idleStart([fauxAssistantMessage(fauxToolCall("big", {})), () => fauxAssistantMessage("third")], [towerDoSlim]);
	await session.prompt("go");
	expireCache();
	await session.prompt("again?");
	finish();

	assert.deepEqual(sessionManager.getEntries().filter((entry: any) => entry.type === "custom" && entry.customType === "context-fold").map((entry: any) => entry.data.trigger), ["idle"]);
	assert.ok(!JSON.stringify(requests.at(-1).messages).includes("Open tasks: a"));
});
