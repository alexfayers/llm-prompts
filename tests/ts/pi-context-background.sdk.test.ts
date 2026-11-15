import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, test } from "node:test";
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, type ExtensionAPI, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { useEnv } from "./helpers.ts";
import { Background, registerBackgroundHooks } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/background.ts";
import { registerFork } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/fork.ts";
import { registryOf } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";

const STUB = join(import.meta.dirname, "fixtures/fork-stub.mjs");
const eventually = async (done: () => boolean, ms = 8000) => {
	for (let waited = 0; !done() && waited < ms; waited += 10) await new Promise((resolve) => setTimeout(resolve, 10));
	assert.ok(done(), "condition not reached");
};
const quiet = () => new Promise((resolve) => setTimeout(resolve, 150));
const ui = new Proxy({}, { get: () => () => undefined }) as never;

useEnv({ PI_HERDSMAN_MAILBOX: undefined, PI_CONTEXT_CHILD: undefined });

const unhandled: unknown[] = [];
const onUnhandled = (reason: unknown) => unhandled.push(reason);
before(() => void process.on("unhandledRejection", onUnhandled));
after(() => void process.off("unhandledRejection", onUnhandled));

/** A session on a faux model that has the fork tools backed by the stub child, and a `pause` tool that blocks until released. */
async function setup(options: { withUi: boolean }) {
	const dir = mkdtempSync(join(tmpdir(), "pi-context-bg-"));
	process.env.PI_CODING_AGENT_DIR = dir;
	const faux = fauxProvider();
	const modelRuntime = await ModelRuntime.create({ authPath: join(dir, "auth.json"), modelsPath: null, refreshOnCreate: false });
	modelRuntime.registerNativeProvider(faux.provider);
	let release = () => {};
	const paused = new Promise<void>((resolve) => (release = resolve));
	const requests: string[] = [];
	let held: Background | undefined;
	const extension = (pi: ExtensionAPI) => {
		const background = (held = new Background(pi));
		registerBackgroundHooks(pi, background);
		registerFork(pi, [process.execPath, STUB], background);
		pi.registerTool({ name: "pause", label: "pause", description: "Blocks until released", parameters: Type.Object({}), execute: async () => (await paused, { content: [{ type: "text", text: "resumed" }], details: {} }) });
	};
	const resourceLoader = new DefaultResourceLoader({ cwd: dir, agentDir: dir, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [extension] });
	await resourceLoader.reload();
	const { session } = await createAgentSession({ cwd: dir, agentDir: dir, model: faux.getModel(), modelRuntime, resourceLoader, sessionManager: SessionManager.inMemory(dir), settingsManager: SettingsManager.inMemory({}), tools: ["fork", "fork_cancel", "pause"] });
	await session.bindExtensions(options.withUi ? { uiContext: ui } : {});
	const reply = (text: string) => (context: unknown) => (requests.push(JSON.stringify(context)), fauxAssistantMessage(text));
	const gate = (name: string) => join(dir, name);
	const open = (name: string) => writeFileSync(gate(name), "");
	const forks = (...names: string[]) => names.map((name) => fauxToolCall("fork", { task: `STUB_GATE:${gate(name)}`, name, background: true }));
	const finished = (name: string) => registryOf().all().find((run) => run.name === name)?.state === "done";
	const end = async () => {
		await session.extensionRunner.emit({ type: "session_shutdown", reason: "quit" });
		session.dispose();
		rmSync(dir, { recursive: true });
	};
	return { faux, session, requests, reply, open, forks, finished, release, end, background: () => held! };
}

describe("background forks in a session", () => {
	test("without a UI the session holds at settle and continues once for each finished run", async () => {
		const { faux, session, requests, reply, open, forks, end } = await setup({ withUi: false });
		faux.setResponses([fauxAssistantMessage(forks("sa", "sb")), reply("waiting"), reply("got sa"), reply("got sb")]);
		const prompting = session.prompt("go");
		await eventually(() => requests.length === 1);
		open("sa");
		await eventually(() => requests.length === 2);
		assert.match(requests[1], /\[fork sa done\]/);
		open("sb");
		await prompting;
		assert.equal(requests.length, 3);
		assert.match(requests[2], /\[fork sb done\]/);
		assert.deepEqual(unhandled, []);
		await end();
	});

	test("session.abort does not reach the hold, but cancelling the live runs releases it without another request", async () => {
		const { faux, session, requests, reply, forks, background, end } = await setup({ withUi: false });
		faux.setResponses([fauxAssistantMessage(forks("ha")), reply("waiting"), reply("never")]);
		const prompting = session.prompt("go");
		await eventually(() => requests.length === 1);
		await quiet();
		assert.equal(background().cancel("ha")?.state, "cancelled");
		await prompting;
		assert.equal(requests.length, 1);
		await end();
	});

	test("with a UI each finished run wakes the idle session, while the other is still live", async () => {
		const { faux, session, requests, reply, open, forks, end } = await setup({ withUi: true });
		faux.setResponses([fauxAssistantMessage(forks("ua", "ub")), reply("waiting"), reply("got ua"), reply("got ub")]);
		await session.prompt("go");
		assert.equal(requests.length, 1);
		open("ua");
		await eventually(() => requests.length === 2);
		await session.waitForIdle();
		assert.match(requests[1], /\[fork ua done\]/);
		open("ub");
		await eventually(() => requests.length === 3);
		await session.waitForIdle();
		assert.match(requests[2], /\[fork ub done\]/);
		assert.deepEqual(unhandled, []);
		await end();
	});

	test("with a UI a result that arrives while the session is busy is delivered after its run, in one request", async () => {
		const { faux, session, requests, reply, open, forks, finished, release, end } = await setup({ withUi: true });
		faux.setResponses([fauxAssistantMessage([...forks("ba", "bb"), fauxToolCall("pause", {})]), reply("one"), reply("two")]);
		const prompting = session.prompt("go");
		await eventually(() => registryOf().live().length === 2);
		open("ba");
		open("bb");
		await eventually(() => finished("ba") && finished("bb"));
		await quiet();
		assert.equal(requests.length, 0);
		release();
		await prompting;
		await session.waitForIdle();
		assert.equal(requests.length, 2);
		assert.match(requests[1], /\[fork ba done\][\s\S]*\[fork bb done\]/);
		assert.deepEqual(unhandled, []);
		await end();
	});
});
