import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mock, test } from "node:test";
import { fauxAssistantMessage, fauxProvider, fauxText, fauxThinking, fauxToolCall, type FauxResponseStep } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, type ExtensionAPI, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import contextFold from "../../src/llm_prompts/prompts/pi/extensions/context-fold.ts";
import { useEnv } from "./helpers.ts";

useEnv({ CONTEXT_FOLD: "on", CONTEXT_FOLD_PENDING_TOKENS: "100", CONTEXT_FOLD_KEEP_TOKENS: "1200", PI_CONTEXT_CHILD: undefined, CONTEXT_FOLD_IDLE: undefined, CONTEXT_FOLD_IDLE_MIN_TOKENS: "100", PI_CACHE_RETENTION: undefined });

const BIG = "z".repeat(4000);

async function start(...responses: FauxResponseStep[]) {
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
	const { session, sessionManager, requests, finish } = await start(...TWO_BIG_CALLS, () => fauxAssistantMessage("again"));
	await session.prompt("go");
	await session.prompt("again?");
	finish();

	const entries = sessionManager.getEntries();
	assert.deepEqual(entries.filter((entry) => entry.type === "custom" && entry.customType === "context-fold").map((entry: any) => entry.data.mode), ["on"]);
	const messages: any[] = requests.at(-1).messages;
	const sent = JSON.stringify(messages);
	assert.ok(/\[folded: big \{\} -> 4000 chars; result_fetch\(\{ref:\\"fold-[^"\\]+\\"\}\) resends it, transcript\(\) shows the steps around it\]/.test(sent));
	assert.equal(sent.split(BIG).length - 1, 1);
	assert.ok(sent.includes("T1") && !sent.includes("T2") && !sent.includes("T3"));
	const calls = messages.flatMap((message) => (message.role === "assistant" ? message.content.filter((block: any) => block.type === "toolCall").map((block: any) => block.id) : []));
	assert.deepEqual(calls.sort(), messages.filter((message) => message.role === "toolResult").map((message) => message.toolCallId).sort());
});

test("pi accepts the undo of a fold after a rejected request and the request after it holds the full results again", async () => {
	const { session, sessionManager, requests, finish } = await start(
		...TWO_BIG_CALLS,
		() => fauxAssistantMessage("", { stopReason: "error", errorMessage: "400 thinking block rejected" }),
		() => fauxAssistantMessage("third"),
	);
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

test("pi accepts the pruning of an aborted message and the next request holds its one-line stub", async () => {
	const PLAN = "plan ".repeat(300);
	const { session, sessionManager, requests, finish } = await start(fauxAssistantMessage(PLAN, { stopReason: "aborted" }), ...TWO_BIG_CALLS, () => fauxAssistantMessage("again"));
	await session.prompt("go");
	await session.prompt("go on");
	await session.prompt("again?");
	finish();

	assert.ok(sessionManager.getEntries().some((entry: any) => entry.type === "custom" && entry.customType === "context-fold"));
	const sent = JSON.stringify(requests.at(-1).messages);
	assert.ok(sent.includes("[abandoned: plan plan"));
	assert.ok(!sent.includes(PLAN));
});

const CACHE_EXPIRY_MS = 10 * 60_000;

function idleStart(...responses: FauxResponseStep[]) {
	process.env.CONTEXT_FOLD_PENDING_TOKENS = "1000000";
	let skew = 0;
	const now = Date.now;
	mock.method(Date, "now", () => now() + skew);
	return start(...TWO_BIG_CALLS, ...responses).then((started) => ({ ...started, expireCache: () => void (skew += CACHE_EXPIRY_MS), finish: () => (mock.restoreAll(), started.finish()) }));
}

const upToLastUser = (messages: any[]): string => JSON.stringify(messages.slice(0, messages.map((message) => message.role).lastIndexOf("user") + 1));

test("pi accepts the idle fold of the first request and the next request holds the same messages up to the prompt", async () => {
	const { session, sessionManager, requests, expireCache, finish } = await idleStart(fauxAssistantMessage([fauxThinking("T4"), fauxToolCall("big", {})]), fauxAssistantMessage([fauxThinking("T5"), fauxText("ok")]));
	await session.prompt("go");
	expireCache();
	await session.prompt("again?");
	finish();

	assert.ok(requests.slice(0, 3).every((request) => !JSON.stringify(request.messages).includes("[folded:")));
	const [first, second] = requests.slice(3);
	assert.equal(JSON.stringify(first.messages).split(BIG).length - 1, 1);
	assert.equal(upToLastUser(first.messages), upToLastUser(second.messages));
	assert.deepEqual(sessionManager.getEntries().filter((entry: any) => entry.type === "custom" && entry.customType === "context-fold").map((entry: any) => entry.data.trigger), ["idle"]);
});

test("a rejected idle fold is not saved and folding stops", async () => {
	const { session, sessionManager, requests, expireCache, finish } = await idleStart(() => fauxAssistantMessage("", { stopReason: "error", errorMessage: "400 thinking block rejected" }), () => fauxAssistantMessage("third"));
	await session.prompt("go");
	expireCache();
	await session.prompt("again?");
	expireCache();
	await session.prompt("once more?");
	finish();

	assert.equal(sessionManager.getEntries().filter((entry: any) => entry.type === "custom" && entry.customType === "context-fold").length, 0);
	assert.equal(JSON.stringify(requests.at(-1).messages).split(BIG).length - 1, 2);
});
