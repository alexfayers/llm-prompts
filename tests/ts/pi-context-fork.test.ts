import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { after, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { ROLES } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/roles.ts";
import { prefixHash, trackPrefix } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/bridge.ts";
import { registryOf } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";
import { coldArgs, registerFork, seedEntries } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/fork.ts";

const user = (id: string) => ({ type: "message", id, message: { role: "user", content: id } });
const assistantCalling = (id: string, ...calls: string[]) => ({ type: "message", id, message: { role: "assistant", content: calls.map((call) => ({ type: "toolCall", id: call })) } });
const result = (id: string, call: string) => ({ type: "message", id, message: { role: "toolResult", toolCallId: call } });

describe("seedEntries", () => {
	test("a call nested in another, like one from codemode, cuts before its parent's message", () => {
		const branch = [user("u1"), assistantCalling("a1", "c1"), result("r1", "c1"), assistantCalling("a2", "c2"), result("r2", "c2")];
		assert.deepEqual(seedEntries(branch as any, "c2/1").map((entry) => entry.id), ["u1", "a1", "r1"]);
	});
});

describe("coldArgs", () => {
	test("starts a worker with its own session directory, only the role's skills and the role card appended", () => {
		const role = { ...ROLES.reader, skills: ["alpha", "beta"] };
		assert.deepEqual(coldArgs(role, { model: "prov/mod:low", sessionDir: "/s", cardFile: "/c.md", skillsDir: "/skills" }), [
			"--mode", "rpc", "--session-dir", "/s", "--model", "prov/mod:low",
			"--no-skills", "--skill", "/skills/alpha", "--skill", "/skills/beta",
			"--append-system-prompt", "/c.md", "--no-mcp",
		]);
	});
});

const STUB = path.join(import.meta.dirname, "fixtures/fork-stub.mjs");
const agentDir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-fork-"));
after(() => fs.rmSync(agentDir, { recursive: true }));
useEnv({ PI_CODING_AGENT_DIR: agentDir, PI_HERDSMAN_MAILBOX: undefined, PI_CONTEXT_CHILD: undefined, PI_CONTEXT_KEEP_FORKS: undefined, PI_CONTEXT_MCP_PROXY: undefined });

const branch = [user("u1"), assistantCalling("a1", "c1"), result("r1", "c1"), assistantCalling("a2", "call-id")];
const forkDirs = () => fs.readdirSync(path.join(agentDir, "pi-context"), { recursive: true });

const MAIN_TOOLS = [{ name: "mcp__semble__search", description: "d", parameters: {}, exposure: "codemode" }, { name: "read", description: "r", parameters: {}, exposure: "direct" }];

async function fork(params: Record<string, unknown>, cwd = process.cwd(), main = { activeTools: ["read", "codemode"], allTools: MAIN_TOOLS }) {
	const tools: Record<string, any> = {};
	const appended: unknown[][] = [];
	registerFork(
		{
			registerTool: (tool: any) => (tools[tool.name] = tool),
			appendEntry: (...args: unknown[]) => appended.push(args),
			getThinkingLevel: () => "high",
			getActiveTools: () => main.activeTools,
			getAllTools: () => main.allTools,
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

	test("a cold worker leaves no session or fork files behind", async () => {
		await fork({ task: "STUB_REPORT", model: "prov/cheap" });
		assert.deepEqual(fs.readdirSync(path.join(agentDir, "pi-context")).filter((file) => file !== "worktrees"), []);
	});

	test("tells the child its role and run id, and records the run with its outcome in the registry", async () => {
		const seen = JSON.parse((await fork({ task: "STUB_INSPECT", name: "inspect" })).tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
		assert.equal(seen.env.role, "reader");
		assert.match(seen.env.runId, /^[0-9a-f]{8}$/);
		assert.equal(registryOf().all().find((run) => run.id === seen.env.runId)?.state, "done");
		await fork({ task: "STUB_REPORT", name: "reported" });
		await fork({ task: "STUB_CRASH", name: "crashed" });
		const byName = (name: string) => registryOf().all().find((run) => run.name === name)!;
		assert.deepEqual([byName("reported").state, byName("reported").outcome, byName("reported").ref], ["done", "done", "rc-fork-reported-call-id"]);
		assert.equal(byName("crashed").state, "failed");
		assert.equal(registryOf().live().length, 0);
	});

	test("a setup failure leaves no files and no bridge socket behind", async () => {
		process.env.PI_CONTEXT_MCP_PROXY = "1";
		const before = forkDirs();
		const failed = (await fork({ task: "hi", name: "setup" }, process.cwd(), { activeTools: [], allTools: undefined as never })).tool;
		assert.ok(failed instanceof Error);
		assert.match(failed.message, /fork setup failed/);
		assert.deepEqual(forkDirs(), before);
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

	describe("as a cold worker", () => {
		const seen = async (params: Record<string, unknown>, ...rest: [string?, any?]) => JSON.parse((await fork({ task: "STUB_INSPECT", model: "prov/cheap", ...params }, ...rest)).tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
		const main = { activeTools: ["read", "edit", "codemode", "mcp__semble__search", "mcp__builder_mcp__TaskeiCreateTask"], allTools: [...MAIN_TOOLS, { name: "mcp__builder_mcp__TaskeiCreateTask", description: "w", parameters: {}, exposure: "codemode" }] };
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

		test("a cold writer starts in its worktree and lands through the same queue", async () => {
			const { tool, appended } = await fork({ task: "STUB_WRITE", role: "writer", name: "cold", model: "prov/cheap" }, repo);
			const text = (appended[0][1] as { text: string }).text;
			assert.equal(text.split("\ncwd ")[1], JSON.parse(text.split("\n")[1]).worktree);
			assert.match(tool.content[0].text, /\[merge: landed [0-9a-f]{9}\]/);
		});

		test("a failure before the child starts names the kept worktree", async () => {
			process.env.PI_CONTEXT_MCP_PROXY = "1";
			const failed = (await fork({ task: "hi", role: "writer", name: "early" }, repo, { activeTools: [], allTools: undefined as never })).tool;
			assert.ok(failed instanceof Error);
			assert.match(failed.message, /fork early failed[\s\S]*worktree [^\s]+early kept/);
			assert.ok(fs.existsSync(failed.message.match(/worktree ([^\s]+) kept/)![1]));
		});
	});
});
