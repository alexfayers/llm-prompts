import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { after, before, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { ROLES } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/roles.ts";
import { prefixHash, trackPrefix } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/bridge.ts";
import { registryOf } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";
import { Background } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/background.ts";
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

async function fork(params: Record<string, unknown>, cwd = process.cwd(), main = { activeTools: ["read", "codemode"], allTools: MAIN_TOOLS }, appendEntry?: () => void) {
	const tools: Record<string, any> = {};
	const appended: unknown[][] = [];
	const sent: any[][] = [];
	const pi = {
		registerTool: (tool: any) => (tools[tool.name] = tool),
		appendEntry: appendEntry ?? ((...args: unknown[]) => appended.push(args)),
		sendMessage: (...args: unknown[]) => sent.push(args),
		getThinkingLevel: () => "high",
		getActiveTools: () => main.activeTools,
		getAllTools: () => main.allTools,
	} as any;
	const background = new Background(pi);
	registerFork(pi, [process.execPath, STUB], background);
	const ctx = {
		cwd,
		isIdle: () => true,
		getSystemPrompt: () => "<mcp_servers>\nsemble (codemode)\n</mcp_servers>",
		executeTool: async (name: string, args: unknown) => ({ result: { content: [{ type: "text", text: `ran ${name} ${JSON.stringify(args)}` }], details: {} }, isError: false }),
		model: { provider: "prov", id: "mod" },
		sessionManager: { getBranch: () => branch, getHeader: () => ({ type: "session", version: 3, id: "main-id", timestamp: "t", cwd }) },
	};
	return { tool: await tools.fork.execute("call-id", params, undefined, undefined, ctx).catch((error: Error) => error), appended, sent, tools, background, ctx };
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

	test("records the delegate's files directory and model in the registry", async () => {
		const seen = JSON.parse((await fork({ task: "STUB_INSPECT", name: "recorded", model: "prov/cheap" })).tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
		const run = registryOf().all().find((run) => run.name === "recorded")!;
		assert.deepEqual([run.files, run.model], [path.dirname(seen.args[seen.args.indexOf("--session-dir") + 1]), "prov/cheap"]);
	});

	test("a setup failure leaves no files and no bridge socket behind", async () => {
		process.env.PI_CONTEXT_MCP_PROXY = "1";
		const before = forkDirs();
		const failed = (await fork({ task: "hi", name: "setup" }, process.cwd(), { activeTools: [], allTools: undefined as never })).tool;
		assert.ok(failed instanceof Error);
		assert.match(failed.message, /fork setup failed/);
		assert.deepEqual(forkDirs(), before);
	});

	describe("in the background", () => {
		const eventually = async (done: () => boolean) => {
			for (let attempt = 0; attempt < 500 && !done(); attempt++) await new Promise((resolve) => setTimeout(resolve, 10));
		};
		const unhandled: unknown[] = [];
		const onUnhandled = (reason: unknown) => unhandled.push(reason);
		before(() => void process.on("unhandledRejection", onUnhandled));
		after(() => void process.off("unhandledRejection", onUnhandled));

		test("returns at once and wakes main with the result when the run ends", async () => {
			const { tool, sent, appended } = await fork({ task: "STUB_REPORT", name: "bg", background: true });
			assert.equal(tool.content[0].text, "started fork bg (background)");
			assert.equal(registryOf().all().find((run) => run.name === "bg")?.background, true);
			await eventually(() => sent.length > 0);
			assert.deepEqual(sent, [[{ customType: "pi-context-results", content: "[fork bg done] ref rc-fork-bg-call-id", display: true }, { triggerTurn: true }]]);
			assert.equal(registryOf().all().find((run) => run.name === "bg")?.state, "done");
			assert.deepEqual(appended, [["result-cap", { ref: "rc-fork-bg-call-id", text: "OUTCOME done ref:rc-fork-x\nbody line" }]]);
		});

		test("a run whose result cannot be saved is still finished and wakes main", async () => {
			const { sent } = await fork({ task: "STUB_REPORT", name: "nosave", background: true }, process.cwd(), undefined, () => {
				throw new Error("stale");
			});
			await eventually(() => sent.length > 0);
			assert.equal(registryOf().all().find((run) => run.name === "nosave")?.state, "done");
			assert.equal(sent.length, 1);
		});

		test("a crashing child wakes main with an error and raises no unhandled rejection", async () => {
			const { sent } = await fork({ task: "STUB_CRASH", name: "boom", background: true });
			await eventually(() => sent.length > 0);
			assert.match(sent[0][0].content, /^\[fork boom failed\] .*ref/);
			assert.equal(registryOf().all().find((run) => run.name === "boom")?.state, "failed");
			assert.deepEqual(unhandled, []);
		});

		test("fork_cancel stops a live run without waking main", async () => {
			const { tools, sent } = await fork({ task: "STUB_HANG", name: "slow", background: true });
			const cancelled = await tools.fork_cancel.execute("c", { name: "slow" }, undefined, undefined, {});
			assert.equal(cancelled.content[0].text, "cancelled fork slow");
			assert.equal(registryOf().all().find((run) => run.name === "slow")?.state, "cancelled");
			await assert.rejects(tools.fork_cancel.execute("c", { name: "slow" }, undefined, undefined, {}), /no live background fork slow/);
			await new Promise((resolve) => setTimeout(resolve, 100));
			assert.deepEqual(sent, []);
		});

		test("fork_steer reaches a live background fork, and an unknown name lists the live forks", async () => {
			const { tools, sent, appended } = await fork({ task: "STUB_STEER", name: "steer", background: true });
			await assert.rejects(tools.fork_steer.execute("s", { name: "nope", message: "m" }), /no live background fork nope\. Live forks: .*steer/);
			await eventually(() => registryOf().all().find((run) => run.name === "steer")?.state === "running");
			await new Promise((resolve) => setTimeout(resolve, 50));
			assert.equal((await tools.fork_steer.execute("s", { name: "steer", message: "look at b" })).content[0].text, "steered fork steer");
			await eventually(() => sent.length > 0);
			assert.match(sent[0][0].content, /^\[fork steer done\]/);
			assert.match(JSON.stringify(appended), /steered: look at b/);
		});

		test("a fork that the session's end stopped keeps its session, and fork_resume continues it", async () => {
			const { tools, sent, appended, background, ctx } = await fork({ task: "STUB_STEER", name: "cut", background: true });
			await new Promise((resolve) => setTimeout(resolve, 50));
			background.shutdown();
			const run = () => registryOf().all().find((candidate) => candidate.name === "cut");
			await eventually(() => run()?.state === "lost");
			await new Promise((resolve) => setTimeout(resolve, 100));
			assert.equal(fs.existsSync(path.join(run()!.files!, "seed.jsonl")), true);
			await assert.rejects(tools.fork_resume.execute("r", { name: "nope" }, undefined, undefined, ctx), /no lost fork nope to resume\. Resumable: .*cut/);
			assert.equal((await tools.fork_resume.execute("r", { name: "cut" }, undefined, undefined, ctx)).content[0].text, "resumed fork cut (background)");
			await eventually(() => sent.length > 0);
			assert.equal(run()?.id, registryOf().all().filter((candidate) => candidate.name === "cut").at(-1)?.id);
			assert.match(JSON.stringify(appended), /echo: Your session stopped before you finished/);
			await eventually(() => !fs.existsSync(run()!.files!));
		});
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

		test("without the proxy, reports whether the child's prefix matches main's last request and flags a mismatch in the result line", async () => {
			delete process.env.PI_CONTEXT_MCP_PROXY;
			trackMain();
			process.env.STUB_PREFIX = prefixHash(mainPayload);
			const matched = (await fork({ task: "x" })).tool;
			assert.equal(matched.details.prefix, "match");
			assert.doesNotMatch(matched.content[0].text, /prefix mismatch/);
			process.env.STUB_PREFIX = "other";
			const missed = (await fork({ task: "x" })).tool;
			delete process.env.STUB_PREFIX;
			assert.equal(missed.details.prefix, "mismatch");
			assert.match(missed.content[0].text, /\[fork [\w-]+: prefix mismatch, cache /);
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

		test("with a target lands its commits on the target and leaves the session repo untouched", async () => {
			const other = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-target-")));
			after(() => fs.rmSync(other, { recursive: true }));
			git(other, "init", "-b", "trunk");
			git(other, "config", "user.email", "t@example.com");
			git(other, "config", "user.name", "t");
			git(other, "commit", "--allow-empty", "-m", "start");
			const before = git(repo, "rev-parse", "HEAD");
			const { tool, appended } = await fork({ task: "STUB_WRITE", role: "writer", name: "elsewhere", target: path.relative(repo, other) }, repo);
			assert.equal(JSON.parse((appended[0][1] as { text: string }).text.split("\n")[1]).repo, other);
			assert.match(tool.content[0].text, /\[merge: landed [0-9a-f]{9}\]/);
			assert.equal(git(other, "log", "-1", "--format=%s", "trunk"), "write");
			assert.equal(git(repo, "rev-parse", "HEAD"), before);
			assert.equal(git(repo, "status", "--porcelain"), "");
		});

		test("a cold writer starts in its worktree and lands through the same queue", async () => {
			const { tool, appended } = await fork({ task: "STUB_WRITE", role: "writer", name: "cold", model: "prov/cheap" }, repo);
			const text = (appended[0][1] as { text: string }).text;
			assert.equal(text.split("\ncwd ")[1], JSON.parse(text.split("\n")[1]).worktree);
			assert.match(tool.content[0].text, /\[merge: landed [0-9a-f]{9}\]/);
		});

		test("a failure before the child starts removes the clean worktree and its branch", async () => {
			process.env.PI_CONTEXT_MCP_PROXY = "1";
			const failed = (await fork({ task: "hi", role: "writer", name: "early" }, repo, { activeTools: [], allTools: undefined as never })).tool;
			assert.ok(failed instanceof Error);
			assert.match(failed.message, /fork early failed[\s\S]*\(worktree removed: clean\)/);
			assert.equal(execFileSync("git", ["-C", repo, "branch", "--list", "fork/early"], { encoding: "utf8" }), "");
		});
	});
});
