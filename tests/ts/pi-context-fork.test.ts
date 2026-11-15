import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { after, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { prefixHash, trackPrefix } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/bridge.ts";
import { registerFork, seedEntries } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/fork.ts";

const user = (id: string) => ({ type: "message", id, message: { role: "user", content: id } });
const assistantCalling = (id: string, ...calls: string[]) => ({ type: "message", id, message: { role: "assistant", content: calls.map((call) => ({ type: "toolCall", id: call })) } });
const result = (id: string, call: string) => ({ type: "message", id, message: { role: "toolResult", toolCallId: call } });


const STUB = path.join(import.meta.dirname, "fixtures/fork-stub.mjs");
const agentDir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-fork-"));
after(() => fs.rmSync(agentDir, { recursive: true }));
useEnv({ PI_CODING_AGENT_DIR: agentDir, PI_HERDSMAN_MAILBOX: undefined, PI_CONTEXT_CHILD: undefined, PI_CONTEXT_KEEP_FORKS: undefined, PI_CONTEXT_MCP_PROXY: undefined });

const branch = [user("u1"), assistantCalling("a1", "c1"), result("r1", "c1"), assistantCalling("a2", "call-id")];
const forkDirs = () => fs.readdirSync(path.join(agentDir, "pi-context"), { recursive: true });

async function fork(params: Record<string, unknown>, cwd = process.cwd()) {
	const tools: Record<string, any> = {};
	const appended: unknown[][] = [];
	registerFork(
		{
			registerTool: (tool: any) => (tools[tool.name] = tool),
			appendEntry: (...args: unknown[]) => appended.push(args),
			getThinkingLevel: () => "high",
			getActiveTools: () => ["read", "codemode"],
			getAllTools: () => [{ name: "mcp__semble__search", description: "d", parameters: {}, exposure: "codemode" }, { name: "read", description: "r", parameters: {}, exposure: "direct" }],
		} as any,
		[process.execPath, STUB],
	);
	const ctx = {
		cwd,
		getSystemPrompt: () => "<mcp_servers>\nsemble (codemode)\n</mcp_servers>",
		executeTool: async (name: string, args: unknown) => ({ result: { content: [{ type: "text", text: `ran ${name} ${JSON.stringify(args)}` }], details: {} }, isError: false }),
		model: { provider: "prov", id: "mod" },
		sessionManager: { getBranch: () => branch, getHeader: () => ({ type: "session", version: 3, id: "main-id", timestamp: "t", cwd }) },
	};
	return { tool: await tools.fork.execute("call-id", params, undefined, undefined, ctx).catch((error: Error) => error), appended };
}

describe("fork tool", () => {
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
		assert.match(seen.prompt, /do not call fork\. You are read-only[\s\S]*STUB_INSPECT$/);
	});

	test("returns the reply cut to its outcome with the first request's cache numbers, and keeps the full text by ref", async () => {
		const { tool, appended } = await fork({ task: "STUB_REPORT", name: "x" });
		assert.equal(tool.content[0].text, "OUTCOME done ref:rc-fork-x\n[fork x: cache 100/1, ref rc-fork-x-call-id]");
		assert.deepEqual(appended, [["result-cap", { ref: "rc-fork-x-call-id", text: "OUTCOME done ref:rc-fork-x\nbody line" }]]);
		assert.equal(tool.details.outcome, "done");
		assert.equal(tool.details.usage.cacheRead, 300);
	});

	describe("with the MCP proxy", () => {
		const mainPayload = { system: "s", tools: [{ name: "read" }] };
		const trackMain = () => {
			let handler: any;
			trackPrefix({ on: (_event: string, listener: unknown) => (handler = listener) } as any);
			handler({ payload: mainPayload });
		};
		useEnv({ PI_CONTEXT_MCP_PROXY: "1" });

		test("starts the child without MCP servers and describes main's tools and servers section in the handshake", async () => {
			const { tool } = await fork({ task: "STUB_INSPECT" });
			const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
			assert.equal(seen.args.at(-1), "--no-mcp");
			assert.deepEqual(seen.handshake.bridge, { socket: seen.handshake.bridge.socket, activeTools: ["read", "codemode"], tools: [{ name: "mcp__semble__search", description: "d", parameters: {}, exposure: "codemode" }], section: "semble (codemode)" });
			assert.equal(seen.socketExists, true);
		});

		test("runs the child's MCP calls in main and reports whether its prefix matches main's last request", async () => {
			trackMain();
			process.env.STUB_PREFIX = prefixHash(mainPayload);
			const matched = (await fork({ task: "STUB_BRIDGE" })).tool;
			assert.match(matched.content[0].text, /^echo: ran mcp__semble__search {"query":"q"}/);
			assert.equal(matched.details.prefix, "match");
			process.env.STUB_PREFIX = "other";
			assert.equal((await fork({ task: "STUB_BRIDGE" })).tool.details.prefix, "mismatch");
			delete process.env.STUB_PREFIX;
		});

		test("leaves the child's own MCP servers on when the proxy is off", async () => {
			delete process.env.PI_CONTEXT_MCP_PROXY;
			const { tool } = await fork({ task: "STUB_INSPECT" });
			const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
			assert.equal(seen.args.includes("--no-mcp"), false);
			assert.equal(seen.handshake.bridge, undefined);
		});
	});

	describe("as a writer", () => {
		const git = (cwd: string, ...args: string[]) => execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
		const repo = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-writer-")));
		after(() => fs.rmSync(repo, { recursive: true }));
		useEnv({ PI_CONTEXT_TEST_CMD: "true" });

		test("works in a worktree under the agent directory and lands its commits on the main checkout", async () => {
			git(repo, "init", "-b", "main");
			git(repo, "config", "user.email", "t@example.com");
			git(repo, "config", "user.name", "t");
			git(repo, "commit", "--allow-empty", "-m", "start");
			const { tool, appended } = await fork({ task: "STUB_WRITE", role: "writer", name: "w" }, repo);
			const handshake = JSON.parse((appended[0][1] as { text: string }).text.split("\n")[1]);
			assert.equal(handshake.role, "writer");
			assert.match((appended[0][1] as { text: string }).text, new RegExp(`Your worktree: ${handshake.worktree}`));
			assert.ok(handshake.worktree.startsWith(path.join(agentDir, "pi-context", "worktrees")));
			assert.match(tool.content[0].text, /\[merge: landed [0-9a-f]{9}\]/);
			assert.equal(fs.readFileSync(path.join(repo, fs.readdirSync(repo).find((file) => file.startsWith("written-"))!), "utf8"), "from the fork");
			assert.equal(fs.existsSync(handshake.worktree), false);
		});
	});
});
