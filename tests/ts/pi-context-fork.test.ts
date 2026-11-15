import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { registerFork, seedEntries } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/fork.ts";

const user = (id: string) => ({ type: "message", id, message: { role: "user", content: id } });
const assistantCalling = (id: string, ...calls: string[]) => ({ type: "message", id, message: { role: "assistant", content: calls.map((call) => ({ type: "toolCall", id: call })) } });
const result = (id: string, call: string) => ({ type: "message", id, message: { role: "toolResult", toolCallId: call } });

describe("seedEntries", () => {
	test("cuts before the assistant message holding the fork call and its sibling calls", () => {
		const branch = [user("u1"), assistantCalling("a1", "c1"), result("r1", "c1"), assistantCalling("a2", "c2", "fork-1"), result("r2", "c2")];
		assert.deepEqual(seedEntries(branch as any, "fork-1").map((entry) => entry.id), ["u1", "a1", "r1"]);
	});

	test("keeps the whole branch when the fork call is not on it yet", () => {
		const branch = [user("u1"), assistantCalling("a1", "c1"), result("r1", "c1")];
		assert.equal(seedEntries(branch as any, "fork-1").length, 3);
	});
});

const STUB = path.join(import.meta.dirname, "fixtures/fork-stub.mjs");
const agentDir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-fork-"));
after(() => fs.rmSync(agentDir, { recursive: true }));
useEnv({ PI_CODING_AGENT_DIR: agentDir, PI_HERDSMAN_MAILBOX: undefined, PI_CONTEXT_CHILD: undefined, PI_CONTEXT_KEEP_FORKS: undefined });

const branch = [user("u1"), assistantCalling("a1", "c1"), result("r1", "c1"), assistantCalling("a2", "call-id")];
const forkDirs = () => fs.readdirSync(path.join(agentDir, "pi-context"), { recursive: true });

async function fork(params: Record<string, unknown>) {
	const tools: Record<string, any> = {};
	const appended: unknown[][] = [];
	registerFork({ registerTool: (tool: any) => (tools[tool.name] = tool), appendEntry: (...args: unknown[]) => appended.push(args), getThinkingLevel: () => "high" } as any, [process.execPath, STUB]);
	const ctx = {
		cwd: process.cwd(),
		model: { provider: "prov", id: "mod" },
		sessionManager: { getBranch: () => branch, getHeader: () => ({ type: "session", version: 3, id: "main-id", timestamp: "t", cwd: process.cwd() }) },
	};
	return { tool: await tools.fork.execute("call-id", params, undefined, undefined, ctx).catch((error: Error) => error), appended };
}

describe("fork tool", () => {
	test("the extension registers it, also in a delegate so the declared tools match", async () => {
		assert.ok((await loadExtension("pi-context/index")).tools.fork);
	});

	test("starts a reader child on the seed with main's model, thinking level and directory", async () => {
		const { tool } = await fork({ task: "STUB_INSPECT" });
		const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
		assert.deepEqual(seen.args.slice(0, 2), ["--mode", "rpc"]);
		assert.deepEqual(seen.args.slice(4), ["--model", "prov/mod", "--thinking", "high"]);
		assert.equal(seen.cwd, process.cwd());
		assert.deepEqual(seen.handshake, { role: "reader" });
		assert.equal(seen.handshakeMode, 0o600);
		assert.equal(seen.seed[0].cwd, process.cwd());
		assert.notEqual(seen.seed[0].id, "main-id");
		assert.deepEqual(seen.seed.slice(1).map((entry: any) => entry.id), ["u1", "a1", "r1"]);
		assert.match(seen.prompt, /read-only delegate[\s\S]*STUB_INSPECT$/);
	});

	test("returns the reply cut to its outcome with the first request's cache numbers, and keeps the full text by ref", async () => {
		const { tool, appended } = await fork({ task: "STUB_REPORT", name: "x" });
		assert.equal(tool.content[0].text, "OUTCOME done ref:rc-fork-x\n[fork x: cache 100/1, ref rc-fork-x-call-id]");
		assert.deepEqual(appended, [["result-cap", { ref: "rc-fork-x-call-id", text: "OUTCOME done ref:rc-fork-x\nbody line" }]]);
		assert.equal(tool.details.outcome, "done");
		assert.equal(tool.details.usage.cacheRead, 300);
	});

	test("removes its files after the child ends unless PI_CONTEXT_KEEP_FORKS is set", async () => {
		await fork({ task: "hi" });
		assert.deepEqual(forkDirs(), []);
		process.env.PI_CONTEXT_KEEP_FORKS = "1";
		await fork({ task: "hi" });
		assert.equal(forkDirs().length, 3);
	});

	test("refuses inside a delegate and reports a failed child", async () => {
		process.env.PI_HERDSMAN_MAILBOX = "/mailbox";
		assert.match((await fork({ task: "hi" })).tool.message, /top-level/);
		delete process.env.PI_HERDSMAN_MAILBOX;
		const dead = (await fork({ task: "STUB_CRASH", name: "dead" })).tool
		assert.match(dead.message, /fork dead failed/);
	});
});
