import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { after, afterEach, before, beforeEach, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { projectResult } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/outcome.ts";
import { ROLES } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/roles.ts";
import { trackPrefix } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/bridge.ts";
import { isLive, MAIN_TOOLS_WAIT, registryOf, type Run } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";
import { Background } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/background.ts";
import { briefReason, coldArgs, coldLabel, FANOUT_EXTRA, KEEP_FINISHED_MS, SHARED_FILE_MAX_CHARS, registerFork, WARM_FORK_MAX_TOKENS, resolveModel, seedEntries, summarizeSession, sweepFinished } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/fork.ts";
import { LONG_CACHE_MS } from "../../src/llm_prompts/prompts/pi/extensions/context-fold.ts";

const user = (id: string) => ({ type: "message", id, message: { role: "user", content: id } });
const assistantCalling = (id: string, ...calls: string[]) => ({ type: "message", id, message: { role: "assistant", content: calls.map((call) => ({ type: "toolCall", id: call })) } });
const result = (id: string, call: string) => ({ type: "message", id, message: { role: "toolResult", toolCallId: call } });

describe("seedEntries", () => {
	test("a call nested in another, like one from codemode, cuts before its parent's message", () => {
		const branch = [user("u1"), assistantCalling("a1", "c1"), result("r1", "c1"), assistantCalling("a2", "c2"), result("r2", "c2")];
		assert.deepEqual(seedEntries(branch as any, "c2/1").map((entry) => entry.id), ["u1", "a1", "r1"]);
	});
});

describe("seedEntries after a compaction", () => {
	test("a warm fork gets the last compaction's kept entries, the compaction and what follows, not the history before", () => {
		const compaction = (id: string, firstKeptEntryId: string) => ({ type: "compaction", id, firstKeptEntryId, summary: id });
		const branch = [user("u0"), user("u1"), compaction("k1", "u1"), user("u2"), user("u3"), compaction("k2", "u3"), user("u4"), assistantCalling("a1", "c1")];
		assert.deepEqual(seedEntries(branch as any, "c1").map((entry) => entry.id), ["u3", "k2", "u4"]);
	});

	test("the lead's saved state from before the compaction stays in the chain ahead of the kept entries", () => {
		const saved = (id: string, customType: string, data: object = { hidden: [id] }) => ({ type: "custom", id, customType, data });
		const link = (parentId: string | null, entry: object) => ({ ...entry, parentId });
		const kept = { type: "message", id: "u2", message: { role: "toolResult", content: "[capped: 9 chars, ref rc-c9; result_fetch]" } };
		const branch = [
			link(null, saved("h1", "hide-tools")),
			link("h1", saved("t1", "hide-tools")),
			link("t1", saved("p1", "pending-asks", { action: "add", id: "a1", text: "still open" })),
			link("p1", saved("r1", "result-cap", { ref: "rc-c9", text: "kept result" })),
			link("r1", saved("r2", "result-cap", { ref: "rc-c1", text: "compacted result" })),
			link("r2", saved("x1", "context-fold", {})),
			link("x1", user("u1")),
			link("u1", kept),
			link("u2", { type: "compaction", id: "k1", firstKeptEntryId: "u2", summary: "k1" }),
			link("k1", assistantCalling("a1", "c1")),
		];
		const seed = seedEntries(branch as any, "c1") as any[];
		assert.deepEqual(seed.map((entry) => entry.id), ["h1", "t1", "p1", "r1", "u2", "k1"]);
		assert.deepEqual(seed.map((entry) => entry.parentId), [null, "h1", "t1", "p1", "r1", "u2"]);
	});
});

describe("briefReason", () => {
	test("stops at the first word that would pass the length limit", () => {
		assert.equal(briefReason("the branch averyveryveryverylongbranchname was not pushed"), "the branch");
	});
});

describe("resolveModel", () => {
	const agentDir = fs.mkdtempSync(path.join(os.tmpdir(), "fork-tiers-"));
	fs.mkdirSync(path.join(agentDir, "pi-context"));
	fs.writeFileSync(path.join(agentDir, "pi-context", "models.json"), JSON.stringify({ sol: "acme/sol-2", opus: "acme/opus" }));

	test("a tier resolves to its installed model, and a provider/id stays literal", () => {
		assert.equal(resolveModel("sol", agentDir), "acme/sol-2");
		assert.equal(resolveModel("other/sol:high", agentDir), "other/sol:high");
		assert.equal(resolveModel("sol:high", agentDir), "acme/sol-2:high");
	});

	test("an unknown tier fails, listing the valid tiers", () => {
		assert.throws(() => resolveModel("zeta", agentDir), /unknown model tier zeta: use provider\/id or one of opus, sol/);
	});

	test("the label names the tier and its model and says the worker shares no context", () => {
		assert.equal(coldLabel("x", "sol", "acme/sol-2"), "cold worker x on sol = acme/sol-2 (no shared context)");
		assert.equal(coldLabel("x", "acme/m", "acme/m"), "cold worker x on acme/m (no shared context)");
	});
});

describe("summarizeSession", () => {
	test("streams the summary through the model registry, so providers that extensions register are used", async () => {
		const model = { provider: "acme", id: "m", api: "acme-api", maxTokens: 1000, reasoning: false };
		const streamed: unknown[] = [];
		const modelRegistry = { streamSimple: (...args: unknown[]) => (streamed.push(args[0]), { result: async () => ({ role: "assistant", content: [{ type: "text", text: "SUMMARY" }], stopReason: "stop" }) }) };
		assert.equal(await summarizeSession({ model, modelRegistry } as any, [user("u1")] as any), "SUMMARY");
		assert.deepEqual(streamed, [model]);
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
const agentDir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-fork-")));
after(() => fs.rmSync(agentDir, { recursive: true }));
useEnv({ PI_CODING_AGENT_DIR: agentDir, PI_CONTEXT_CHILD: undefined });
const PROXY_ON = { llmPrompts: { forks: { mcpProxy: true } } };
let settings: object = {};
let mainContext = 1000;
let leadModel = "mod";
const MODEL_COSTS: Record<string, { input: number; cacheRead: number }> = { mod: { input: 3, cacheRead: 0.3 }, cheap: { input: 0.01, cacheRead: 0.001 }, dear: { input: 1000, cacheRead: 100 } };
afterEach(() => {
	settings = {};
	mainContext = 1000;
	leadModel = "mod";
});
const FORKS_FILE = path.join(agentDir, "pi-context", "forks.json");
const limit = (maxLive: unknown) => (fs.mkdirSync(path.dirname(FORKS_FILE), { recursive: true }), fs.writeFileSync(FORKS_FILE, JSON.stringify({ maxLive })));
afterEach(() => fs.rmSync(FORKS_FILE, { force: true }));

const branch = [user("u1"), assistantCalling("a1", "c1"), result("r1", "c1"), assistantCalling("a2", "call-id")];
const forkDirs = () => fs.readdirSync(path.join(agentDir, "pi-context"), { recursive: true });

const MAIN_TOOLS = [{ name: "mcp__semble__search", description: "d", parameters: {}, exposure: "codemode" }, { name: "read", description: "r", parameters: {}, exposure: "direct" }];

const reads: string[] = [];
/** What pi's read tool returns: at most 2000 lines, from the 1-based `offset`, with a note naming the next offset when it stops early. */
function readLikePi(text: string, offset = 1, limit?: number): string {
	const lines = text.split("\n");
	const count = Math.min(limit ?? Infinity, 2000);
	const shown = lines.slice(offset - 1, offset - 1 + count);
	const next = offset + shown.length;
	if (next > lines.length) return shown.join("\n");
	return `${shown.join("\n")}\n\n[Showing lines ${offset}-${next - 1} of ${lines.length}. Use offset=${next} to continue.]`;
}
let deniedReads: string[] = [];
const STUB_SUFFIX = 'That is all the shared context. Once you have read it, call reply with {"outcome":"done","ref":""} and stop. Your specific task arrives next.';

const eventually = async (done: () => boolean) => {
	for (let attempt = 0; attempt < 500 && !done(); attempt++) await new Promise((resolve) => setTimeout(resolve, 10));
};

/** Waits for the runs a start result names, then gives their reply as a result. */
async function settle(started: any, appended: unknown[][], sent: any[][]): Promise<any> {
	if (started instanceof Error) return started;
	const latest = (name: string) => registryOf().all().filter((run) => run.name === name).at(-1);
	const names = [started.details.name, ...(started.details.tasks ?? [])];
	await eventually(() => names.every((name) => latest(name) && !isLive(latest(name)!)));
	const run = latest(started.details.name)!;
	const text = (appended.find(([type, entry]) => type === "result-cap" && (entry as any).ref === run.ref)?.[1] as any)?.text ?? "";
	const digest = sent.map(([message]) => message.content).filter((content: string) => content.startsWith(`[fork ${run.name} `)).join("\n");
	return { content: [{ type: "text", text }], details: { ...started.details, ...run, digest } };
}

async function start(params: Record<string, unknown>, cwd = process.cwd(), main = { activeTools: ["read", "codemode"], allTools: MAIN_TOOLS }, appendEntry?: () => void, contextTokens?: number, summarize: () => Promise<string> = async () => "SUMMARY OF MAIN", signal?: AbortSignal) {
	const tools: Record<string, any> = {};
	const appended: unknown[][] = [];
	const sent: any[][] = [];
	const handlers: Record<string, (...args: any[]) => unknown> = {};
	const pi = {
		on: (event: string, handler: (...args: any[]) => unknown) => (handlers[event] = handler),
		registerTool: (tool: any) => (tools[tool.name] = tool),
		appendEntry: appendEntry ?? ((...args: unknown[]) => appended.push(args)),
		sendMessage: (...args: unknown[]) => sent.push(args),
		getThinkingLevel: () => "high",
		getSettings: () => settings,
		getActiveTools: () => main.activeTools,
		getAllTools: () => main.allTools,
	} as any;
	const background = new Background(pi);
	registerFork(pi, [process.execPath, STUB], background, summarize);
	const ctx = {
		cwd,
		isIdle: () => true,
		getSystemPrompt: () => "<mcp_servers>\nsemble (codemode)\n</mcp_servers>",
		executeTool: async (name: string, args: any) => {
			if (name !== "read") return { result: { content: [{ type: "text", text: `ran ${name} ${JSON.stringify(args)}` }], details: {} }, isError: false };
			reads.push(args.path);
			if (deniedReads.some((denied) => args.path.includes(denied))) return { result: { content: [{ type: "text", text: "blocked by permission rules" }], details: {} }, isError: true };
			const text = fs.readFileSync(args.path, "utf8");
			if (text.startsWith("CAPPED")) return { result: { content: [{ type: "text", text: "[capped: 99999 chars, ref rc-x; result_fetch({ref, offset?, limit?, pattern?})]" }], details: {} }, isError: false };
			if (text.startsWith("IMAGE")) return { result: { content: [{ type: "image", data: "", mimeType: "image/png" }], details: {} }, isError: false };
			return { result: { content: [{ type: "text", text: readLikePi(text, args.offset, args.limit) }], details: {} }, isError: false };
		},
		model: { provider: "prov", id: leadModel, cost: MODEL_COSTS[leadModel] },
		modelRegistry: { find: (_provider: string, id: string) => ({ contextWindow: 200_000, cost: MODEL_COSTS[id] }) },
		getContextUsage: () => ({ tokens: contextTokens ?? mainContext, contextWindow: 200_000, percent: 0 }),
		sessionManager: { getBranch: () => branch, getHeader: () => ({ type: "session", version: 3, id: "main-id", timestamp: "t", cwd }) },
	};
	const execute = tools.fork.execute;
	tools.fork = { ...tools.fork, execute: async (...args: unknown[]) => settle(await execute(...args), appended, sent) };
	return { tool: await execute("call-id", params, signal, undefined, ctx).catch((error: Error) => error), appended, sent, tools, background, ctx, handlers, launch: (more: Record<string, unknown>) => execute(`call-${randomUUID()}`, more, undefined, undefined, ctx) };
}

async function fork(...args: Parameters<typeof start>) {
	const started = await start(...args);
	return { ...started, tool: await settle(started.tool, started.appended, started.sent) };
}

describe("fork tool", () => {
	beforeEach(() => {
		registryOf().restore([]);
		fs.rmSync(path.join(agentDir, "pi-context", "stubs"), { recursive: true, force: true });
	});

	test("writes the valid entries of the readMcp setting into the handshake", async () => {
		const good = { tool: "mcp__demo__exec", argsMatch: { command: "read .*" } };
		settings = { llmPrompts: { forks: { readMcp: [good, { tool: "mcp__demo__bad", argsMatch: { command: "(" } }] } } };
		const { tool } = await fork({ task: "STUB_INSPECT" });
		assert.deepEqual(JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, "")).handshake.readMcp, [good]);
	});

	test("warns on stderr about dropped readMcp entries when there is no UI", async () => {
		settings = { llmPrompts: { forks: { readMcp: [{ tool: "mcp__demo__bad", argsMatch: { command: "(" } }] } } };
		const written: string[] = [];
		const original = process.stderr.write;
		process.stderr.write = ((chunk: string) => (written.push(String(chunk)), true)) as typeof process.stderr.write;
		try {
			await fork({ task: "STUB_INSPECT" });
		} finally {
			process.stderr.write = original;
		}
		assert.match(written.join(""), /pi-context: dropped invalid llmPrompts\.forks\.readMcp entries: .*mcp__demo__bad/);
	});

	test("starts a reader child on the seed with main's model, thinking level and directory", async () => {
		const { tool } = await fork({ task: "STUB_INSPECT" });
		const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
		assert.deepEqual(seen.args.slice(0, 2), ["--mode", "rpc"]);
		assert.deepEqual(seen.args.slice(4), ["--model", "prov/mod", "--thinking", "high"]);
		assert.equal(seen.cwd, process.cwd());
		assert.deepEqual(seen.handshake, { role: "reader", inherited: "r1", model: "prov/mod", thinking: "high", readMcp: [] });
		assert.equal(seen.handshakeMode, 0o600);
		assert.equal(seen.seed[0].cwd, process.cwd());
		assert.notEqual(seen.seed[0].id, "main-id");
		assert.deepEqual(seen.seed.slice(1).map((entry: any) => entry.id), ["u1", "a1", "r1"]);
		assert.match(seen.prompt, /do not call fork\. You are read-only[\s\S]*STUB_INSPECT$/);
	});

	describe("as a delegate", () => {
		const bridge = { socket: "/main/b.sock", activeTools: ["read", "fork", "mcp__semble__search"], tools: [{ name: "mcp__semble__search", description: "d", parameters: {}, exposure: "codemode" }] };
		const delegate = (role: string) => {
			const file = path.join(agentDir, `${role}-handshake.json`);
			fs.writeFileSync(file, JSON.stringify({ role, bridge }));
			return file;
		};
		const asRole = (role: string) => useEnv(() => ({ PI_CONTEXT_CHILD: delegate(role), PI_CONTEXT_ROLE: role }));

		describe("a team", () => {
			asRole("team");

			test("forks a member that calls main's MCP bridge directly and cannot fork", async () => {
				const { tool } = await fork({ task: "STUB_INSPECT" });
				const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
				assert.equal(seen.handshake.role, "reader");
				assert.deepEqual(seen.handshake.bridge, { ...bridge, activeTools: ["read", "mcp__semble__search"] });
				assert.ok(seen.args.includes("--no-mcp"));
				assert.equal(seen.env.role, "reader");
				assert.equal((await start({ task: "x", role: "team" })).tool.message, "A team cannot start a team.");
			});
		});

		for (const role of ["reader", "writer"]) {
			describe(`a ${role}`, () => {
				asRole(role);

				test("cannot fork", async () => {
					const { tool, tools, ctx } = await start({ task: "STUB_INSPECT" });
					assert.equal(tool.message, "Only the top-level session or a team can fork.");
					for (const [name, params] of [["fork_cancel", { name: "x" }], ["fork_resume", { name: "x" }], ["fork_steer", { name: "x", message: "y" }]] as const) {
						await assert.rejects(tools[name].execute("c", params, undefined, undefined, ctx), /Only the top-level session or a team can/);
					}
				});
			});
		}
	});

	test("a warm fork over the token limit starts cold on main's model with a summary of the session", async () => {
		const { tool } = await fork({ task: "STUB_INSPECT" }, process.cwd(), undefined, undefined, WARM_FORK_MAX_TOKENS + 1);
		const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
		assert.equal(seen.args[seen.args.indexOf("--model") + 1], "prov/mod:high");
		assert.equal(seen.seed, undefined);
		assert.match(seen.prompt, /SUMMARY OF MAIN[\s\S]*STUB_INSPECT$/);
		assert.match(tool.details.model, /prov\/mod:high/);
	});

	test("a large fork returns before its summary is written, and forks of one snapshot share the summary call", async () => {
		let calls = 0;
		let written!: (summary: string) => void;
		const pending = new Promise<string>((resolve) => (written = resolve));
		const summarize = () => (calls++, pending);
		const { tool, tools, ctx, appended, sent } = await start({ task: "STUB_INSPECT", name: "big1" }, process.cwd(), undefined, undefined, WARM_FORK_MAX_TOKENS + 1, summarize);
		assert.equal(tool.details.background, true);
		assert.equal(registryOf().all().find((run) => run.name === "big1")?.state, "running");
		const second = tools.fork.execute("call-id", { task: "STUB_INSPECT", name: "big2" }, undefined, undefined, ctx);
		await new Promise((resolve) => setTimeout(resolve, 50));
		written("SHARED SUMMARY");
		const [first, other] = await Promise.all([settle(tool, appended, sent), second]);
		assert.equal(calls, 1);
		for (const reply of [first, other]) assert.match(JSON.parse(reply.content[0].text.split("\n")[0].replace(/^echo: /, "")).prompt, /SHARED SUMMARY/);
	});

	test("a large fork keeps running when its tool call aborts after it launched", async () => {
		const controller = new AbortController();
		const { tools, ctx } = await start({ task: "STUB_HANG", name: "biglate" }, process.cwd(), undefined, undefined, WARM_FORK_MAX_TOKENS + 1, undefined, controller.signal);
		await new Promise((resolve) => setTimeout(resolve, 200));
		controller.abort();
		assert.equal(registryOf().all().find((run) => run.name === "biglate")?.state, "running");
		await tools.fork_cancel.execute("c", { name: "biglate" }, undefined, undefined, ctx);
	});

	test("a large fork cancelled while its summary is written starts no child", async () => {
		let written!: (summary: string) => void;
		const { tools, ctx, sent } = await start({ task: "STUB_INSPECT", name: "bigcancel" }, process.cwd(), undefined, undefined, WARM_FORK_MAX_TOKENS + 1, () => new Promise<string>((resolve) => (written = resolve)));
		await tools.fork_cancel.execute("c", { name: "bigcancel" }, undefined, undefined, ctx);
		written("LATE");
		await new Promise((resolve) => setTimeout(resolve, 100));
		assert.equal(registryOf().all().find((run) => run.name === "bigcancel")?.state, "cancelled");
		assert.deepEqual(sent, []);
	});

	test("a warm fork at the token limit stays warm", async () => {
		const { tool } = await fork({ task: "STUB_INSPECT" }, process.cwd(), undefined, undefined, WARM_FORK_MAX_TOKENS);
		const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
		assert.deepEqual(seen.seed.slice(1).map((entry: any) => entry.id), ["u1", "a1", "r1"]);
	});

	test("keeps the full reply by ref and records its outcome", async () => {
		const { tool, appended } = await fork({ task: "STUB_REPORT", name: "x" });
		assert.deepEqual(appended, [["result-cap", { ref: "rc-fork-x-call-id", text: "OUTCOME done ref:rc-fork-x\nbody line" }]]);
		assert.equal(tool.details.outcome, "done");
		assert.equal(tool.details.digest, "[fork x done] body line ref rc-fork-x-call-id\n0 forks still running.");
	});

	test("a reply call's arguments decide the outcome and the kept reply, whatever the text says", async () => {
		const { tool, appended } = await fork({ task: 'STUB_REPLY:{"outcome":"found-it","ref":"pr-1","verdict":"CLEAN","asks":["Which?"],"text":"ASK: an example"}', name: "replied" });
		assert.equal(tool.content[0].text, "OUTCOME found-it ref:pr-1\nVerdict: CLEAN\nASK: Which?\nASK: an example");
		assert.deepEqual(appended.filter(([type]) => type === "pending-asks").map(([, entry]) => (entry as any).text), ["replied: Which?"]);
		assert.equal(tool.details.outcome, "found-it");
		const failed = await fork({ task: 'STUB_REPORT STUB_REPLY:{"outcome":"failed","ref":""}', name: "replyfailed" });
		assert.equal(failed.tool.details.outcome, "failed");
	});

	test("a finished cold worker keeps its files for a day after it finished, so its cost can be audited", async () => {
		await fork({ task: "STUB_REPORT", name: "swept", model: "prov/cheap" });
		const files = registryOf().all().find((run) => run.name === "swept")!.files!;
		assert.equal(fs.existsSync(path.join(files, "finished")), true);
		sweepFinished(path.join(agentDir, "pi-context"), Date.now() + LONG_CACHE_MS + 1);
		assert.equal(fs.existsSync(files), true);
		sweepFinished(path.join(agentDir, "pi-context"), Date.now() + KEEP_FINISHED_MS + 1);
		assert.equal(fs.existsSync(files), false);
	});

	test("keeps only child accounting entries in the usage store after the run files expire", async () => {
		await fork({ task: "STUB_REPORT", name: "kept" });
		const run = registryOf().all().find((entry) => entry.name === "kept")!;
		sweepFinished(path.join(agentDir, "pi-context"), Date.now() + KEEP_FINISHED_MS + 1);
		const copy = path.join(agentDir, "sessions", "pi-context", `kept-${run.id}.jsonl`);
		const header = JSON.parse(fs.readFileSync(copy, "utf8").trim());
		const archive = path.join(agentDir, "pi-context", "kept", `${header.piContextUsage.sourceHash}.jsonl`);
		assert.deepEqual(fs.readFileSync(archive, "utf8").trim().split("\n").slice(1).map((line) => JSON.parse(line).id), ["u1", "a1", "r1"]);
	});

	test("retention failure preserves the reply and full run without a sweep marker", async (t) => {
		const usage = path.join(agentDir, "sessions", "pi-context");
		const hidden = `${usage}-saved`;
		fs.renameSync(usage, hidden);
		fs.writeFileSync(usage, "not a directory");
		const warning = t.mock.method(console, "warn", () => undefined);
		try {
			const { tool } = await fork({ task: "STUB_REPORT", name: "recovery" });
			assert.match(tool.content[0].text, /OUTCOME done/);
			const run = registryOf().all().find((entry) => entry.name === "recovery")!;
			assert.equal(fs.existsSync(path.join(run.files!, "seed.jsonl")), true);
			assert.equal(fs.existsSync(path.join(run.files!, "finished")), false);
			sweepFinished(path.join(agentDir, "pi-context"), Date.now() + KEEP_FINISHED_MS + 1);
			assert.equal(fs.existsSync(run.files!), true);
			assert.match(String(warning.mock.calls[0].arguments[0]), /keeping the full run for recovery/);
		} finally { fs.unlinkSync(usage); fs.renameSync(hidden, usage); }
	});

	test("tells the child its role and run id, and records the run with its outcome in the registry", async () => {
		const seen = JSON.parse((await fork({ task: "STUB_INSPECT", name: "inspect" })).tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
		assert.equal(seen.env.role, "reader");
		assert.equal(seen.env.worktree, undefined);
		assert.match(seen.env.runId, /^[0-9a-f]{8}$/);
		assert.equal(registryOf().all().find((run) => run.id === seen.env.runId)?.state, "failed");
		await fork({ task: "STUB_REPORT", name: "reported" });
		await fork({ task: "STUB_CRASH", name: "crashed" });
		const byName = (name: string) => registryOf().all().find((run) => run.name === name)!;
		assert.deepEqual([byName("reported").state, byName("reported").outcome, byName("reported").ref], ["done", "done", "rc-fork-reported-call-id"]);
		assert.equal(byName("crashed").state, "failed");
		assert.equal(registryOf().live().length, 0);
		await fork({ task: "plain reply", name: "unreported" });
		assert.equal(byName("unreported").state, "failed");
	});

	test("records the delegate's files directory and model in the registry", async () => {
		const seen = JSON.parse((await fork({ task: "STUB_INSPECT", name: "recorded", model: "prov/cheap" })).tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
		const run = registryOf().all().find((run) => run.name === "recorded")!;
		assert.deepEqual([run.files, run.model], [path.dirname(path.dirname(seen.args[seen.args.indexOf("--session") + 1])), "prov/cheap"]);
	});

	test("a setup failure leaves no files and no bridge socket behind", async () => {
		settings = PROXY_ON;
		const before = forkDirs();
		const failed = (await fork({ task: "hi", name: "setup" }, process.cwd(), { activeTools: [], allTools: undefined as never })).tool;
		assert.equal(failed.details.state, "failed");
		assert.match(failed.details.digest, /^\[fork setup failed\]/);
		assert.deepEqual(forkDirs().filter((dir) => !String(dir).includes("worktrees")), before);
	});

	describe("from a finished fork", () => {
		const inspect = (tool: any) => JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));

		test("a warm source's seed is copied into a new child on the source's model, which keeps the source's inherited", async () => {
			const { tool: source, tools, ctx } = await fork({ task: "STUB_INSPECT", name: "src" });
			const sourceSeed = inspect(source).seed;
			const child = inspect(await tools.fork.execute("call-2", { task: "STUB_INSPECT", name: "kid", from: "src" }, undefined, undefined, { ...ctx, model: { provider: "other", id: "x" } }));
			assert.deepEqual(child.args.slice(4, 8), ["--model", "prov/mod", "--thinking", "high"]);
			assert.notEqual(child.seed[0].id, sourceSeed[0].id);
			assert.deepEqual(child.seed[0].piContextFork, { parentSessionId: sourceSeed[0].id, inherited: "r1" });
			assert.deepEqual(child.seed.slice(1), sourceSeed.slice(1));
			assert.equal(child.handshake.inherited, "r1");
			assert.equal(child.prompt, "Task: STUB_INSPECT");
			const [src, kid] = ["src", "kid"].map((name) => registryOf().all().find((run) => run.name === name)!);
			assert.notEqual(kid.files, src.files);
		});

		test("shared with tasks runs one cold stub on the shared text, then one child per task on a copy of its session", async () => {
			const { tool } = await fork({ shared: "STUB_REPORT notes", tasks: [{ name: "t1", task: "STUB_INSPECT" }, { name: "t2", task: "STUB_INSPECT" }], model: "prov/cheap:low", name: "stub" });
			const run = (name: string) => registryOf().all().find((candidate) => candidate.name === name)!;
			assert.equal(run("stub").task, `STUB_REPORT notes\n\n${STUB_SUFFIX}`);
			assert.equal(tool.content[0].text, "OUTCOME done ref:rc-fork-x\nbody line");
			for (const name of ["t1", "t2"]) assert.equal(JSON.parse(fs.readFileSync(path.join(run(name).files!, "session", "session.jsonl"), "utf8").split("\n")[0]).piContextFork.parentSessionId, run("stub").id);
			assert.equal(fs.existsSync(path.join(run("stub").files!, "finished")), true);
			assert.match(String((await fork({ shared: "s", tasks: [{ name: "t3", task: "x" }] })).tool), /shared needs tasks and model, without task or from/);
		});

		test("sharedFiles puts each file's contents into the stub's prompt, relative to the working directory", async () => {
			const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-shared-files-"));
			fs.mkdirSync(path.join(dir, "sub"));
			fs.writeFileSync(path.join(dir, "a.txt"), "ALPHA\n");
			fs.writeFileSync(path.join(dir, "sub", "b.txt"), "BETA\n");
			await fork({ shared: "STUB_REPORT notes", sharedFiles: ["a.txt", "sub/b.txt"], tasks: [{ name: "sf1", task: "STUB_REPORT" }], model: "prov/cheap", name: "sfstub" }, dir);
			assert.equal(registryOf().all().find((run) => run.name === "sfstub")!.task, `STUB_REPORT notes\n\nFile a.txt:\nALPHA\n\nFile sub/b.txt:\nBETA\n\n${STUB_SUFFIX}`);
		});

		test("sharedFiles names a file that cannot be read before anything starts", async () => {
			const { tool } = await fork({ shared: "s", sharedFiles: ["missing.txt"], tasks: [{ name: "sf2", task: "x" }], model: "prov/cheap", name: "sfmiss" });
			assert.match(String(tool), /cannot read shared file missing\.txt/);
			assert.equal(registryOf().all().some((run) => run.name === "sfmiss"), false);
		});

		test("sharedFiles are read through the read tool, so its permission rules apply", async () => {
			const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-shared-perm-"));
			fs.writeFileSync(path.join(dir, "secret.txt"), "TOPSECRET");
			reads.length = 0;
			deniedReads = ["secret.txt"];
			try {
				const { tool } = await fork({ shared: "s", sharedFiles: ["secret.txt"], tasks: [{ name: "sp1", task: "x" }], model: "prov/cheap", name: "spstub" }, dir);
				assert.deepEqual(reads, [path.join(dir, "secret.txt")]);
				assert.match(String(tool), /cannot read shared file secret\.txt: blocked by permission rules/);
				assert.equal(registryOf().all().some((run) => run.name === "spstub"), false);
			} finally {
				deniedReads = [];
			}
		});

		test("sharedFiles reads a file longer than one read page in full", async () => {
			const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-shared-pages-"));
			const body = Array.from({ length: 4500 }, (_, at) => `line ${at + 1}`).join("\n");
			fs.writeFileSync(path.join(dir, "long.txt"), body);
			await fork({ shared: "STUB_REPORT", sharedFiles: ["long.txt"], tasks: [{ name: "sg1", task: "STUB_REPORT" }], model: "prov/cheap", name: "sgstub" }, dir);
			const task = registryOf().all().find((run) => run.name === "sgstub")!.task;
			assert.ok(task.includes(`File long.txt:\n${body}\n\n`), "the whole file is in the prompt");
			assert.doesNotMatch(task, /Use offset=/);
		});

		test("sharedFiles fails on a capped result or an image", async () => {
			const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-shared-odd-"));
			fs.writeFileSync(path.join(dir, "capped.txt"), "CAPPED");
			fs.writeFileSync(path.join(dir, "pic.png"), "IMAGE");
			for (const [file, message] of [["capped.txt", /shared file capped\.txt was capped/], ["pic.png", /shared file pic\.png is not text/]] as const) {
				const { tool } = await fork({ shared: "s", sharedFiles: [file], tasks: [{ name: "sh1", task: "x" }], model: "prov/cheap", name: "shstub" }, dir);
				assert.match(String(tool), message);
			}
			assert.equal(registryOf().all().some((run) => run.name === "shstub"), false);
		});

		test("sharedFiles fails clearly on a file over the size cap", async () => {
			const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-shared-big-"));
			fs.writeFileSync(path.join(dir, "big.txt"), "x".repeat(SHARED_FILE_MAX_CHARS + 1));
			const { tool } = await fork({ shared: "s", sharedFiles: ["big.txt"], tasks: [{ name: "sb1", task: "x" }], model: "prov/cheap", name: "sbstub" }, dir);
			assert.match(String(tool), new RegExp(`shared file big\\.txt is over ${SHARED_FILE_MAX_CHARS} characters`));
			assert.equal(registryOf().all().some((run) => run.name === "sbstub"), false);
		});

		test("PI_CONTEXT_SHARED=off leaves shared and tasks out of the fork tool and refuses them", async () => {
			const offered = async () => (await start({})).tools.fork;
			assert.deepEqual([Object.keys((await offered()).parameters.properties).filter((key) => ["shared", "tasks"].includes(key)), /shared with tasks/.test((await offered()).description)], [["shared", "tasks"], true]);
			process.env.PI_CONTEXT_SHARED = "off";
			try {
				const tool = await offered();
				assert.deepEqual([Object.keys(tool.parameters.properties).filter((key) => ["shared", "tasks"].includes(key)), /shared with tasks/.test(tool.description)], [[], false]);
				assert.match(String((await fork({ shared: "s", tasks: [{ name: "t1", task: "x" }], model: "prov/cheap" })).tool), /fork needs task/);
			} finally {
				delete process.env.PI_CONTEXT_SHARED;
			}
		});

		test("a stub that replies exactly as its prompt asks lets the tasks start", async () => {
			const { tool } = await fork({ shared: "STUB_COMPLY notes", tasks: [{ name: "k1", task: "STUB_REPORT" }], model: "prov/cheap", name: "kstub" });
			assert.equal(tool.content[0].text, "OUTCOME done ref:");
			assert.equal(registryOf().all().find((run) => run.name === "k1")?.state, "done");
		});

		test("a fan-out bills the stub's turns once, to the stub, for warm and cold sources", async () => {
			await fork({ shared: "STUB_REPORT notes", tasks: [{ name: "f1", task: "STUB_REPORT" }, { name: "f2", task: "STUB_REPORT" }], model: "prov/cheap", name: "fstub" });
			const { tools, ctx } = await fork({ task: "STUB_REPORT STUB_TURN", name: "wsrc" });
			await tools.fork.execute("call-2", { task: "STUB_REPORT", name: "w1", from: "wsrc" }, undefined, undefined, ctx);
			const billed = (name: string) => {
				const run = registryOf().all().find((candidate) => candidate.name === name)!;
				return fs.readFileSync(path.join(agentDir, "sessions", "pi-context", `${name}-${run.id}.jsonl`), "utf8").trim().split("\n").slice(1).map((line) => JSON.parse(line).id);
			};
			const stub = registryOf().all().find((candidate) => candidate.name === "fstub")!;
			assert.deepEqual(billed("fstub"), [`a-${stub.id}`]);
			for (const name of ["f1", "f2"]) assert.deepEqual(billed(name), [`a-${registryOf().all().find((candidate) => candidate.name === name)!.id}`]);
			assert.deepEqual([billed("wsrc"), billed("w1")], [[`a-${registryOf().all().find((candidate) => candidate.name === "wsrc")!.id}`], []]);
		});

		test("shared rejects a task name used twice or taken by the stub, before starting anything", async () => {
			for (const [name, tasks] of [["dstub", [{ name: "d1", task: "x" }, { name: "d1", task: "y" }]], ["dstub", [{ name: "dstub", task: "x" }]]] as const) {
				assert.match(String((await fork({ shared: "s", tasks, model: "prov/cheap", name })).tool), /task names must be unique and differ from the stub's: (d1|dstub)/);
			}
			assert.equal(registryOf().all().some((run) => run.name === "dstub"), false);
		});

		test("from fails with a model, and with a name that has no finished fork", async () => {
			await fork({ task: "STUB_REPORT", name: "done1" });
			assert.match(String((await fork({ task: "x", from: "done1", model: "prov/cheap" })).tool), /from runs at the source's model and effort: drop model/);
			assert.match(String((await fork({ task: "x", from: "nope" })).tool), /no finished fork nope\. Finished: done1/);
		});

		test("a cold source's session is copied into each child's own files, which continue it on the source's model and effort", async () => {
			const { tools, ctx } = await fork({ shared: "STUB_REPORT notes", tasks: [{ name: "c0", task: "STUB_REPORT" }], name: "csrc", model: "prov/cheap:low" });
			const source = registryOf().all().find((run) => run.name === "csrc")!;
			const children = await Promise.all(["c1", "c2"].map(async (name) => inspect(await tools.fork.execute("call-2", { task: "STUB_INSPECT", name, from: "csrc" }, undefined, undefined, ctx))));
			const files = ["c1", "c2"].map((name) => registryOf().all().find((run) => run.name === name)!.files!);
			assert.deepEqual(children.map((child) => child.args.slice(0, 6)), files.map((dir) => ["--mode", "rpc", "--session", path.join(dir, "session", "session.jsonl"), "--model", "prov/cheap:low"]));
			assert.equal(children[0].prompt, "Task: STUB_INSPECT");
			const lines = (dir: string) => fs.readFileSync(path.join(dir, "session", "session.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line));
			const [header, ...rest] = lines(source.files!);
			for (const dir of files) {
				const [copied] = lines(dir);
				assert.notEqual(copied.id, header.id);
				assert.equal(copied.piContextFork.parentSessionId, header.id);
				assert.deepEqual(lines(dir).slice(1, rest.length + 1), rest);
			}
			assert.deepEqual(children.map(({ handshake }) => [handshake.inherited, handshake.cacheKey]), [[undefined, header.id], [undefined, header.id]]);
			const grandchild = inspect(await tools.fork.execute("call-3", { task: "STUB_INSPECT", name: "c3", from: "c1" }, undefined, undefined, ctx));
			assert.equal(grandchild.handshake.cacheKey, header.id);
			const runs = ["csrc", "c1", "c2", "c3"].map((name) => registryOf().all().find((run) => run.name === name)!);
			assert.deepEqual(runs.map((entry) => [entry.from, entry.cacheKey]), [[undefined, undefined], ...Array(3).fill(["csrc", header.id])]);
		});

		test("cold forks on one model and effort start from one stub, built once even when they start together", async () => {
			const { tools, ctx } = await start({ task: "STUB_REPORT", name: "warm" });
			const cold = (name: string, model: string) => tools.fork.execute("call-2", { task: "STUB_REPORT", name, model }, undefined, undefined, ctx);
			await Promise.all([cold("cs1", "prov/cheap:low"), cold("cs2", "prov/cheap:low"), cold("cs3", "prov/cheap:low"), cold("cs4", "prov/cheap:high")]);
			const runs = registryOf().all();
			const stubs = runs.filter((run) => run.name.startsWith("stub-")).sort((a, b) => a.model!.localeCompare(b.model!));
			assert.deepEqual(stubs.map((stub) => stub.model), ["prov/cheap:high", "prov/cheap:low"]);
			assert.deepEqual(["cs1", "cs2", "cs3", "cs4"].map((name) => runs.find((run) => run.name === name)?.from), [stubs[1].name, stubs[1].name, stubs[1].name, stubs[0].name]);
		});

		test("cold forks of two sessions that start together share one published stub", async () => {
			const sessions = await Promise.all(["s1", "s2"].map((name) => start({ task: "STUB_REPORT", name, model: "prov/cheap" })));
			await eventually(() => ["s1", "s2"].every((name) => registryOf().all().find((run) => run.name === name)?.state === "done"));
			const runs = registryOf().all();
			const stubs = runs.filter((run) => run.name.startsWith("stub-"));
			assert.equal(stubs.length, 1);
			assert.deepEqual(["s1", "s2"].map((name) => runs.find((run) => run.name === name)?.from), [stubs[0].name, stubs[0].name]);
			assert.deepEqual(fs.readdirSync(path.join(agentDir, "pi-context", "stubs")), [stubs[0].name.slice("stub-".length)]);
			assert.equal(sessions.length, 2);
		});

		test("a stale lock of a dead build is replaced, and a live one makes the fork wait for the stub", async () => {
			const stubs = path.join(agentDir, "pi-context", "stubs");
			await fork({ task: "STUB_REPORT", name: "l1", model: "prov/cheap" });
			const [published] = fs.readdirSync(stubs);
			fs.rmSync(path.join(stubs, published), { recursive: true });
			const lock = path.join(stubs, `${published}.lock`);
			fs.writeFileSync(lock, "");
			const old = new Date(Date.now() - 10 * 60_000);
			fs.utimesSync(lock, old, old);
			await fork({ task: "STUB_REPORT", name: "l2", model: "prov/cheap" });
			assert.deepEqual(fs.readdirSync(stubs), [published]);
			assert.equal(registryOf().all().filter((run) => run.name.startsWith("stub-")).length, 2);
		});

		test("a changed rules file, ancestor AGENTS.md or SYSTEM.md builds a new stub", async () => {
			const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-prompt-")));
			after(() => fs.rmSync(root, { recursive: true }));
			const cwd = path.join(root, "a", "b");
			fs.mkdirSync(path.join(cwd, ".pi"), { recursive: true });
			const rules = path.join(agentDir, "AGENTS.delegate.md");
			fs.writeFileSync(path.join(agentDir, "AGENTS.md"), "main rules");
			after(() => [rules, path.join(agentDir, "AGENTS.md")].forEach((file) => fs.rmSync(file)));
			const from = (name: string) => registryOf().all().find((run) => run.name === name)?.from;
			const changes = [() => undefined, () => fs.writeFileSync(rules, "a new rule"), () => fs.writeFileSync(path.join(root, "AGENTS.md"), "ancestor rule"), () => fs.writeFileSync(path.join(cwd, ".pi", "SYSTEM.md"), "system prompt")];
			for (const [at, change] of changes.entries()) {
				change();
				await fork({ task: "STUB_REPORT", name: `p${at}`, model: "prov/cheap" }, cwd);
			}
			assert.equal(new Set(changes.map((_, at) => from(`p${at}`))).size, changes.length);
		});

		test("a changed skill description of the role builds a new stub", async () => {
			const role = ROLES.reader;
			const skills = role.skills;
			role.skills = ["demo"];
			const skill = path.join(agentDir, "skills", "demo");
			fs.mkdirSync(skill, { recursive: true });
			after(() => fs.rmSync(skill, { recursive: true }));
			try {
				for (const description of ["first", "second"]) {
					fs.writeFileSync(path.join(skill, "SKILL.md"), `---\nname: demo\ndescription: ${description}\n---\nBody`);
					await fork({ task: "STUB_REPORT", name: `k-${description}`, model: "prov/cheap" });
				}
			} finally {
				role.skills = skills;
			}
			const from = (name: string) => registryOf().all().find((run) => run.name === name)?.from;
			assert.notEqual(from("k-first"), from("k-second"));
		});

		test("a stub published while a build waits for the lock is used, not built again", async () => {
			const stubs = path.join(agentDir, "pi-context", "stubs");
			await fork({ task: "STUB_REPORT", name: "w1", model: "prov/cheap" });
			const [published] = fs.readdirSync(stubs);
			const aside = path.join(agentDir, "stub-aside");
			fs.renameSync(path.join(stubs, published), aside);
			const open = fs.openSync;
			fs.openSync = ((file: fs.PathLike, flags: fs.OpenMode, mode?: fs.Mode) => {
				fs.openSync = open;
				if (String(file).endsWith(".lock")) fs.renameSync(aside, path.join(stubs, published));
				return open(file, flags, mode);
			}) as typeof fs.openSync;
			try {
				await fork({ task: "STUB_REPORT", name: "w2", model: "prov/cheap" });
			} finally {
				fs.openSync = open;
			}
			assert.equal(registryOf().all().filter((run) => run.name.startsWith("stub-")).length, 1);
			assert.equal(fs.existsSync(path.join(stubs, `${published}.lock`)), false);
			assert.equal(registryOf().all().find((run) => run.name === "w2")?.state, "done");
		});

		test("a stub that is still building cannot be steered, cancelled, resumed or forked from by name", async () => {
			process.env.STUB_LOG = path.join(agentDir, "building.log");
			try {
				const { tools, ctx } = await start({ task: "STUB_REPORT", name: "q1", model: "prov/cheap" });
				const stub = registryOf().all().find((run) => run.name.startsWith("stub-"))!;
				assert.equal(isLive(stub), true);
				const calls = [
					() => tools.fork_steer.execute("s", { name: stub.name, message: "x" }, undefined, undefined, ctx),
					() => tools.fork_cancel.execute("c", { name: stub.name }, undefined, undefined, ctx),
					() => tools.fork_resume.execute("r", { name: stub.name }, undefined, undefined, ctx),
					() => tools.fork_resume.execute("r", { name: stub.name, task: "x" }, undefined, undefined, ctx),
					() => tools.fork.execute("f", { task: "x", from: stub.name }, undefined, undefined, ctx),
				];
				for (const call of calls) await assert.rejects(call(), /no (live background|lost|finished) fork/);
				assert.equal(registryOf().get(stub.id)!.next, undefined);
				assert.equal(isLive(registryOf().get(stub.id)!), true);
				await eventually(() => registryOf().all().find((run) => run.name === "q1")?.state === "done");
			} finally {
				delete process.env.STUB_LOG;
			}
		});

		test("the stub is private and immutable: no from or resume reaches it, and children copy it", async () => {
			const { tools, ctx } = await fork({ task: "STUB_REPORT", name: "h1", model: "prov/cheap" });
			const stub = registryOf().all().find((run) => run.name.startsWith("stub-"))!;
			const published = path.join(agentDir, "pi-context", "stubs", stub.name.slice("stub-".length), "session", "session.jsonl");
			const before = fs.readFileSync(published, "utf8");
			assert.equal(stub.stub, true);
			await assert.rejects(tools.fork.execute("call-2", { task: "x", from: stub.name }, undefined, undefined, ctx), /no finished fork/);
			await assert.rejects(tools.fork_resume.execute("r", { name: stub.name, task: "x" }, undefined, undefined, ctx));
			await tools.fork.execute("call-3", { task: "STUB_REPORT", name: "h2", model: "prov/cheap" }, undefined, undefined, ctx);
			assert.equal(fs.readFileSync(published, "utf8"), before);
			assert.notEqual(registryOf().all().find((run) => run.name === "h2")?.files, stub.files);
		});

		test("a follow-up from a writer defaults to the source's target", async () => {
			const other = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-from-target-")));
			const { tools, ctx } = await fork({ task: "STUB_REPORT", role: "writer", name: "wtsrc", target: other });
			await tools.fork.execute("call-2", { task: "STUB_REPORT", name: "wtkid", from: "wtsrc" }, undefined, undefined, ctx);
			assert.equal(registryOf().all().find((run) => run.name === "wtkid")!.target, other);
		});
	});

	describe("in the background", () => {
		const unhandled: unknown[] = [];
		const onUnhandled = (reason: unknown) => unhandled.push(reason);
		before(() => void process.on("unhandledRejection", onUnhandled));
		after(() => void process.off("unhandledRejection", onUnhandled));

		test("returns at once and wakes main with the result when the run ends", async () => {
			const { tool, sent, appended } = await start({ task: "STUB_REPORT", name: "bg" });
			assert.equal(tool.content[0].text, "started fork bg (background)");
			assert.equal(registryOf().all().find((run) => run.name === "bg")?.background, true);
			await eventually(() => sent.length > 0);
			assert.deepEqual(sent, [[{ customType: "pi-context-results", content: "[fork bg done] body line ref rc-fork-bg-call-id\n0 forks still running.", display: true }, { deliverAs: "steer", triggerTurn: true }]]);
			assert.equal(registryOf().all().find((run) => run.name === "bg")?.state, "done");
			assert.deepEqual(appended, [["result-cap", { ref: "rc-fork-bg-call-id", text: "OUTCOME done ref:rc-fork-x\nbody line" }]]);
		});

		test("a stub that finishes sends no message, wakes nobody and adds nothing to the digest", async () => {
			const { sent, appended, background } = await start({ task: "STUB_REPORT", name: "quiet", model: "prov/cheap" });
			await eventually(() => sent.length > 0);
			const stub = registryOf().all().find((run) => run.name.startsWith("stub-"))!;
			assert.equal(stub.state, "done");
			assert.deepEqual(sent.map(([message]) => (message as { content: string }).content.split(" ")[1]), ["quiet"]);
			assert.deepEqual(appended.map(([, entry]) => (entry as { ref: string }).ref), ["rc-fork-quiet-call-id"]);
			assert.doesNotMatch(background.digest() ?? "", /stub-/);
		});

		test("a stub that fails reports its diagnostic under a saved ref", async () => {
			process.env.STUB_BAD_STUB = "1";
			try {
				const { sent, appended } = await start({ task: "STUB_REPORT", name: "unlucky", model: "prov/cheap" });
				await eventually(() => sent.some(([message]) => /^\[fork stub-/.test((message as { content: string }).content)));
				const stub = registryOf().all().find((run) => run.name.startsWith("stub-"))!;
				assert.equal(stub.state, "failed");
				assert.match((sent.find(([message]) => /^\[fork stub-/.test((message as { content: string }).content))![0] as { content: string }).content, new RegExp(`ref ${stub.ref}`));
				assert.ok(appended.some(([, entry]) => (entry as { ref: string }).ref === stub.ref));
			} finally {
				delete process.env.STUB_BAD_STUB;
			}
		});

		test("a run whose result cannot be saved is still finished and wakes main", async () => {
			const { sent } = await start({ task: "STUB_REPORT", name: "nosave" }, process.cwd(), undefined, () => {
				throw new Error("stale");
			});
			await eventually(() => sent.length > 0);
			assert.equal(registryOf().all().find((run) => run.name === "nosave")?.state, "done");
			assert.equal(sent.length, 1);
		});

		test("a crashing child wakes main with an error and raises no unhandled rejection", async () => {
			const { sent } = await start({ task: "STUB_CRASH", name: "boom" });
			await eventually(() => sent.length > 0);
			assert.match(sent[0][0].content, /^\[fork boom failed\] .*ref/);
			assert.equal(registryOf().all().find((run) => run.name === "boom")?.state, "failed");
			assert.deepEqual(unhandled, []);
		});

		test("cold workers started together send their prompts only after the stub's first reply", async () => {
			const log = path.join(agentDir, "warmup.log");
			process.env.STUB_LOG = log;
			const { tools, ctx } = await start({ task: "STUB_REPORT", name: "lead", model: "prov/cheap" });
			await tools.fork.execute("call-2", { task: "STUB_REPORT", name: "follow", model: "prov/cheap" }, undefined, undefined, ctx);
			await eventually(() => ["lead", "follow"].every((name) => registryOf().all().find((run) => run.name === name)?.state === "done"));
			delete process.env.STUB_LOG;
			const ids = Object.fromEntries(registryOf().all().map((run) => [run.name, run.id]));
			const stub = registryOf().all().filter((run) => run.name.startsWith("stub-"));
			const lines = fs.readFileSync(log, "utf8").trim().split("\n").slice(0, 3);
			assert.equal(stub.length, 1);
			assert.deepEqual(lines.slice(0, 2), [`${stub[0].id} prompt`, `${stub[0].id} message_end`]);
			assert.match(lines[2], new RegExp(`^(${ids.lead}|${ids.follow}) prompt$`));
		});

		test("shared with tasks returns at once and starts each task's child once the stub has finished", async () => {
			const { tool, sent } = await start({ shared: "STUB_REPORT notes", tasks: [{ name: "b1", task: "STUB_REPORT" }, { name: "b2", task: "STUB_REPORT" }], model: "prov/cheap", name: "bstub" });
			assert.equal(tool.content[0].text, "started cold worker bstub on prov/cheap (no shared context) (background)\ntasks b1, b2 start when bstub finishes");
			assert.equal(registryOf().all().some((run) => run.name === "b1"), false);
			await eventually(() => sent.length === 3);
			assert.deepEqual(sent.map(([message]) => message.content.split("]")[0]).sort(), ["[fork b1 done", "[fork b2 done", "[fork bstub done"]);
		});

		test("shared with tasks names each task that did not start when the stub fails", async () => {
			const { sent } = await start({ shared: "STUB_CRASH", tasks: [{ name: "n1", task: "STUB_REPORT" }, { name: "n2", task: "STUB_REPORT" }], model: "prov/cheap", name: "cstub" });
			await eventually(() => sent.length === 3);
			assert.deepEqual(sent.map(([message]) => message.content.split("]")[0]).sort(), ["[fork cstub failed", "[fork n1 failed", "[fork n2 failed"]);
			assert.equal(registryOf().all().some((run) => run.name === "n1" && run.state === "failed"), true);
		});

		test("a fork over the installed maxLive returns a queued receipt and starts when a running one finishes", async () => {
			limit(1);
			const gate = path.join(agentDir, "gate-queue");
			const { sent, launch } = await start({ task: `STUB_GATE:${gate}`, name: "first" });
			const queued = await launch({ task: "STUB_REPORT", name: "second" });
			assert.equal(queued.content[0].text, "queued fork second (background): starts when a running fork finishes");
			await new Promise((resolve) => setTimeout(resolve, 150));
			assert.equal(sent.length, 0);
			fs.writeFileSync(gate, "");
			await eventually(() => sent.length === 2);
			assert.deepEqual(sent.map(([message]) => message.content.split("]")[0]), ["[fork first done", "[fork second done"]);
		});

		test("shared with tasks over the limit starts the queued children as the stub and each other finish", async () => {
			limit(1);
			const { tool, sent } = await start({ shared: "STUB_REPORT notes", tasks: [{ name: "q1", task: "STUB_REPORT" }, { name: "q2", task: "STUB_REPORT" }], model: "prov/cheap", name: "qstub" });
			assert.match(tool.content[0].text, /^started cold worker qstub/);
			await eventually(() => sent.length === 3);
			assert.deepEqual(sent.map(([message]) => message.content.split("]")[0]).sort(), ["[fork q1 done", "[fork q2 done", "[fork qstub done"]);
		});

		test("shared with tasks starts every child at once when the stub finishes, however low the limit", async () => {
			limit(1);
			const gates = ["u1", "u2"].map((name) => path.join(agentDir, `gate-${name}`));
			const { sent } = await start({ shared: "STUB_REPORT notes", tasks: gates.map((gate, at) => ({ name: `u${at + 1}`, task: `STUB_GATE:${gate}` })), model: "prov/cheap", name: "ustub" });
			const run = (name: string) => registryOf().all().find((candidate) => candidate.name === name);
			await eventually(() => Boolean(run("u1") && run("u2")));
			assert.deepEqual([run("u1")?.queued, run("u2")?.queued], [undefined, undefined]);
			gates.forEach((gate) => fs.writeFileSync(gate, ""));
			await eventually(() => sent.length === 3);
		});

		test("shared with tasks starts at most FANOUT_EXTRA children over the limit and queues the rest", async () => {
			limit(1);
			const gates = Array.from({ length: FANOUT_EXTRA + 3 }, (_, at) => path.join(agentDir, `gate-o${at}`));
			const { sent } = await start({ shared: "STUB_REPORT notes", tasks: gates.map((gate, at) => ({ name: `o${at}`, task: `STUB_GATE:${gate}` })), model: "prov/cheap", name: "ostub" });
			const children = () => registryOf().all().filter((run) => /^o\d+$/.test(run.name));
			await eventually(() => children().length === gates.length);
			assert.equal(children().filter((run) => !run.queued).length, 1 + FANOUT_EXTRA);
			gates.forEach((gate) => fs.writeFileSync(gate, ""));
			await eventually(() => sent.length === gates.length + 1);
		});

		test("a missing or invalid forks.json leaves the limit at 10", async () => {
			for (const value of [undefined, 0, -1, 1.5, "2"]) {
				value === undefined ? fs.rmSync(FORKS_FILE, { force: true }) : limit(value);
				const gate = path.join(agentDir, `gate-default-${String(value)}`);
				const names = Array.from({ length: 11 }, (_, at) => `d${at}`);
				const { launch } = await start({ task: `STUB_GATE:${gate}`, name: names[0] });
				const receipts = [];
				for (const name of names.slice(1)) receipts.push((await launch({ task: `STUB_GATE:${gate}`, name })).content[0].text);
				assert.deepEqual(receipts.map((text) => text.split(" ")[0]), [...Array(9).fill("started"), "queued"]);
				fs.writeFileSync(gate, "");
				await eventually(() => registryOf().live().length === 0);
				registryOf().restore([]);
			}
		});

		test("fork_cancel stops a queued fork before it starts", async () => {
			limit(1);
			const { tools, sent, launch } = await start({ task: "STUB_HANG", name: "busy" });
			await launch({ task: "STUB_REPORT", name: "waiting" });
			const snapshot = path.join(registryOf().all().find((run) => run.name === "waiting")!.files!, "queued-entries.json");
			assert.equal(fs.existsSync(snapshot), true);
			await tools.fork_cancel.execute("c", { name: "waiting" }, undefined, undefined, {});
			await tools.fork_cancel.execute("c", { name: "busy" }, undefined, undefined, {});
			await new Promise((resolve) => setTimeout(resolve, 100));
			assert.deepEqual(sent, []);
			assert.equal(registryOf().all().find((run) => run.name === "waiting")?.state, "cancelled");
			assert.equal(fs.existsSync(snapshot), false);
		});

		test("fork_cancel stops a live run without waking main", async () => {
			const { tools, sent } = await start({ task: "STUB_HANG", name: "slow" });
			const cancelled = await tools.fork_cancel.execute("c", { name: "slow" }, undefined, undefined, {});
			assert.equal(cancelled.content[0].text, "cancelled fork slow");
			assert.equal(registryOf().all().find((run) => run.name === "slow")?.state, "cancelled");
			await assert.rejects(tools.fork_cancel.execute("c", { name: "slow" }, undefined, undefined, {}), /no live background fork slow/);
			await new Promise((resolve) => setTimeout(resolve, 100));
			assert.deepEqual(sent, []);
		});

		test("fork_steer reaches a live background fork, and an unknown name lists the live forks", async () => {
			const { tools, sent, appended, ctx } = await start({ task: "STUB_STEER", name: "steer" });
			await assert.rejects(tools.fork_steer.execute("s", { name: "nope", message: "m" }), /no live background fork nope\. Live forks: .*steer/);
			await eventually(() => registryOf().all().find((run) => run.name === "steer")?.state === "running");
			await new Promise((resolve) => setTimeout(resolve, 50));
			assert.equal((await tools.fork_steer.execute("s", { name: "steer", message: "look at b" }, undefined, undefined, ctx)).content[0].text, "steered fork steer");
			await eventually(() => sent.length > 0);
			assert.match(sent[0][0].content, /^\[fork steer done\]/);
			assert.match(JSON.stringify(appended), /steered: look at b/);
		});

		test("a fork that the session's end stopped keeps its session, and fork_resume continues it", async () => {
			const { tools, sent, appended, background, ctx } = await start({ task: "STUB_STEER", name: "cut" });
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
			await eventually(() => fs.existsSync(path.join(run()!.files!, "finished")));
			assert.equal(fs.existsSync(path.join(run()!.files!, "finished")), true);
		});

		test("a reload that reload_now requested resumes the forks it ended, and a user reload leaves them lost", async () => {
			const { sent, background, ctx, handlers } = await start({ task: "STUB_HANG", name: "cut" });
			await new Promise((resolve) => setTimeout(resolve, 50));
			background.shutdown();
			const run = () => registryOf().all().find((candidate) => candidate.name === "cut")!;
			await eventually(() => run().state === "lost");
			await new Promise((resolve) => setTimeout(resolve, 100));
			registryOf().update(run().id, { endedBy: "reload" });
			await handlers.session_start({ reason: "reload" }, ctx);
			assert.equal(run().state, "lost");
			const requested = Symbol.for("llm-prompts.reload-now.requested");
			(globalThis as any)[requested] = true;
			try {
				await handlers.session_start({ reason: "reload" }, ctx);
			} finally {
				delete (globalThis as any)[requested];
			}
			assert.equal(run().state, "running");
			assert.deepEqual(sent.map(([message, options]) => [message.content, options]), [["resumed forks: cut", { deliverAs: "nextTurn" }]]);
			background.shutdown();
		});

		describe("a fork that reload_now's reload resumed", () => {
			const waitMs = MAIN_TOOLS_WAIT.ms;
			afterEach(() => void (MAIN_TOOLS_WAIT.ms = waitMs));

			const resumeQueued = async (toolRuns: boolean, lateTool = false) => {
				settings = PROXY_ON;
				limit(1);
				const { tools, sent, background, ctx, handlers, launch } = await start({ task: "STUB_HANG", name: "holder" });
				await launch({ task: "STUB_BRIDGE", name: "waiting" });
				background.shutdown();
				registryOf().update(registryOf().all().find((run) => run.name === "holder")!.id, { state: "cancelled" });
				const waiting = registryOf().all().find((run) => run.name === "waiting")!;
				registryOf().update(waiting.id, { endedBy: "reload" });
				await handlers.session_shutdown({ reason: "reload" });
				if (toolRuns) await tools.fork_cancel.execute("c", { name: "none" }, undefined, undefined, ctx).catch(() => undefined);
				(globalThis as any)[Symbol.for("llm-prompts.reload-now.requested")] = true;
				try {
					await handlers.session_start({ reason: "reload" }, { ...ctx, executeTool: undefined });
				} finally {
					delete (globalThis as any)[Symbol.for("llm-prompts.reload-now.requested")];
				}
				if (lateTool) await (await loadExtension("result-cap")).callTool("result_fetch", { ref: "none" }, ctx as any);
				await eventually(() => sent.some(([message]) => message.content.startsWith("[fork waiting ")));
				return sent.map(([message]) => message.content).find((content) => content.startsWith("[fork waiting "))!;
			};

			test("reaches main's MCP tools once main has run a tool", async () => {
				assert.match(await resumeQueued(true), /echo: ran mcp__semble__search/);
			});

			test("waits for the first tool that main runs, whichever extension registers it", async () => {
				assert.match(await resumeQueued(false, true), /echo: ran mcp__semble__search/);
			});

			test("is told to retry when main runs no tool within the wait", async () => {
				MAIN_TOOLS_WAIT.ms = 50;
				assert.match(await resumeQueued(false), /echo: .*retry/);
			});
		});

		test("a queued fork that a reload dropped before it started is started by fork_resume", async () => {
			limit(1);
			const { tools, sent, appended, background, launch, ctx } = await start({ task: "STUB_HANG", name: "holder" });
			await launch({ task: "STUB_INSPECT", name: "waiting" });
			background.shutdown();
			const run = () => registryOf().all().find((candidate) => candidate.name === "waiting");
			await eventually(() => run()?.state === "lost");
			assert.deepEqual(run()?.queued, { message: "Task: STUB_INSPECT", resume: false });
			const before = JSON.parse(fs.readFileSync(path.join(run()!.files!, "queued-entries.json"), "utf8"));
			assert.deepEqual(before.map((entry: any) => entry.id), ["u1", "a1", "r1", "a2"]);
			branch.push(user("later"), assistantCalling("a3", "c3"));
			assert.equal((await tools.fork_resume.execute("r", { name: "waiting" }, undefined, undefined, ctx)).content[0].text, "resumed fork waiting (background)");
			await eventually(() => sent.length > 0);
			assert.match(sent[0][0].content, /^\[fork waiting /);
			const seed = JSON.parse(String((appended.find(([type, entry]) => type === "result-cap" && (entry as any).ref === run()!.ref)?.[1] as any).text).split("\n")[0].replace(/^echo: /, "")).seed;
			assert.deepEqual(seed.slice(1).map((entry: any) => entry.id), before.map((entry: any) => entry.id));
			assert.equal(run()?.queued, undefined);
			branch.length = 4;
		});

		test("fork_resume of a warm fork whose handshake lost its boundary fails and keeps the handshake", async () => {
			const { tools, sent, background, ctx } = await start({ task: "STUB_STEER", name: "unbound" });
			await new Promise((resolve) => setTimeout(resolve, 50));
			background.shutdown();
			const run = () => registryOf().all().find((candidate) => candidate.name === "unbound");
			await eventually(() => run()?.state === "lost");
			await new Promise((resolve) => setTimeout(resolve, 100));
			const handshake = path.join(run()!.files!, "handshake.json");
			fs.writeFileSync(handshake, JSON.stringify({ role: "reader", readMcp: [] }));
			await tools.fork_resume.execute("r", { name: "unbound" }, undefined, undefined, ctx);
			await eventually(() => sent.length > 0);
			assert.match(sent[0][0].content, /without its inherited boundary/);
			assert.deepEqual(JSON.parse(fs.readFileSync(handshake, "utf8")), { role: "reader", readMcp: [] });
		});

		test("a tier fork records its resolved model, and fork_resume reuses it", async () => {
			fs.writeFileSync(path.join(agentDir, "pi-context", "models.json"), JSON.stringify({ cheap: "prov/cheap" }));
			const { tool, tools, appended, ctx } = await start({ task: "STUB_REPORT", name: "tier", model: "cheap:low" });
			assert.match(tool.content[0].text, /^started cold worker tier on cheap:low = prov\/cheap:low \(no shared context\) \(background\)\ntier starts when stub-\w+ finishes$/);
			await eventually(() => registryOf().all().find((run) => run.name === "tier")?.state === "done");
			assert.equal(registryOf().all().find((run) => run.name === "tier")!.model, "prov/cheap:low");
			const before = appended.length;
			await tools.fork_resume.execute("r", { name: "tier", task: "STUB_INSPECT" }, undefined, undefined, ctx);
			await eventually(() => appended.length > before);
			const seen = JSON.parse((appended.at(-1)![1] as { text: string }).text.replace(/^echo: /, ""));
			assert.deepEqual(seen.args.slice(4, 6), ["--model", "prov/cheap:low"]);
		});

		test("fork_resume with a task continues a finished cold worker on its own session and model", async () => {
			const { tools, sent, appended, ctx } = await fork({ task: "STUB_REPORT", name: "again", model: "prov/cheap" });
			sent.length = 0;
			const continued = await tools.fork_resume.execute("r", { name: "again", task: "STUB_INSPECT" }, undefined, undefined, ctx);
			assert.equal(continued.content[0].text, "continued fork again (background)");
			await eventually(() => sent.length > 0);
			const seen = JSON.parse((appended.at(-1)![1] as { text: string }).text.replace(/^echo: /, ""));
			assert.deepEqual(seen.args.slice(0, 4), ["--mode", "rpc", "--session", path.join(registryOf().all().find((run) => run.name === "again")!.files!, "session", "session.jsonl")]);
			assert.deepEqual(seen.args.slice(4, 6), ["--model", "prov/cheap"]);
			assert.equal(seen.prompt, "Task: STUB_INSPECT");
		});

		test("fork_resume with a task on a running fork queues it, lists it, and starts it after the fork replies", async () => {
			const gate = path.join(agentDir, `gate-queue-${randomUUID()}`);
			const { tools, appended, ctx } = await start({ task: `STUB_GATE:${gate}`, name: "busy", model: "prov/cheap" });
			await eventually(() => registryOf().all().some((run) => run.name === "busy" && isLive(run)));
			const queued = await tools.fork_resume.execute("r", { name: "busy", task: "STUB_INSPECT" }, undefined, undefined, ctx);
			assert.equal(queued.content[0].text, "queued for fork busy (background): STUB_INSPECT starts after it replies");
			assert.equal(registryOf().all().find((run) => run.name === "busy")?.next, "STUB_INSPECT");
			fs.writeFileSync(gate, "");
			await eventually(() => registryOf().all().find((run) => run.name === "busy")?.task === "STUB_INSPECT");
			await eventually(() => appended.some(([, entry]) => /"prompt":"Task: STUB_INSPECT"/.test((entry as { text?: string }).text ?? "")));
			assert.equal(registryOf().all().find((run) => run.name === "busy")?.next, undefined);
			assert.ok(appended.some(([, entry]) => /"prompt":"Task: STUB_INSPECT"/.test((entry as { text?: string }).text ?? "")));
		});

		test("a queued task stays queued when the fork ends blocked, and the result says so", async () => {
			const gate = path.join(agentDir, `gate-blocked-${randomUUID()}`);
			const { tools, ctx } = await start({ task: `STUB_GATE:${gate} STUB_REPLY:{"outcome":"blocked-on-user","ref":""}`, name: "stuck", model: "prov/cheap" });
			await eventually(() => registryOf().all().some((run) => run.name === "stuck" && isLive(run)));
			await tools.fork_resume.execute("r", { name: "stuck", task: "STUB_INSPECT" }, undefined, undefined, ctx);
			fs.writeFileSync(gate, "");
			await eventually(() => registryOf().all().find((run) => run.name === "stuck")?.state === "blocked");
			const run = registryOf().all().find((candidate) => candidate.name === "stuck");
			assert.equal(run?.next, "STUB_INSPECT");
			assert.match(run?.unread ?? "", /queued task kept: STUB_INSPECT/);
		});

		test("a second fork_resume task on a running fork is rejected and names the queued one", async () => {
			const { tools, ctx } = await start({ task: "STUB_HANG", name: "twice", model: "prov/cheap" });
			await eventually(() => registryOf().all().some((run) => run.name === "twice" && isLive(run)));
			await tools.fork_resume.execute("r", { name: "twice", task: "STUB_INSPECT" }, undefined, undefined, ctx);
			await assert.rejects(tools.fork_resume.execute("r", { name: "twice", task: "other" }, undefined, undefined, ctx), /already queued for fork twice: STUB_INSPECT/);
			assert.equal(registryOf().all().find((run) => run.name === "twice")?.next, "STUB_INSPECT");
			await tools.fork_cancel.execute("c", { name: "twice" }, undefined, undefined, ctx);
			await tools.fork_cancel.execute("c", { name: "twice" }, undefined, undefined, ctx);
		});

		test("fork_cancel drops a queued task before it stops the fork", async () => {
			const { tools, ctx } = await start({ task: "STUB_HANG", name: "hung", model: "prov/cheap" });
			await eventually(() => registryOf().all().some((run) => run.name === "hung" && isLive(run)));
			await tools.fork_resume.execute("r", { name: "hung", task: "STUB_INSPECT" }, undefined, undefined, ctx);
			const dropped = await tools.fork_cancel.execute("c", { name: "hung" }, undefined, undefined, ctx);
			assert.equal(dropped.content[0].text, "dropped the queued task of fork hung: STUB_INSPECT");
			assert.equal(registryOf().all().find((run) => run.name === "hung")?.state, "running");
			assert.equal(registryOf().all().find((run) => run.name === "hung")?.next, undefined);
			assert.match((await tools.fork_cancel.execute("c", { name: "hung" }, undefined, undefined, ctx)).content[0].text, /^cancelled fork hung/);
		});

		test("fork_steer on a finished fork continues it with the message", async () => {
			const { tools, appended, background, ctx } = await start({ task: "STUB_REPORT", name: "done", model: "prov/cheap" });
			ctx.isIdle = () => false;
			await eventually(() => registryOf().all().find((run) => run.name === "done")?.state === "done");
			const steered = await tools.fork_steer.execute("s", { name: "done", message: "STUB_INSPECT" }, undefined, undefined, ctx);
			assert.equal(steered.content[0].text, "continued fork done (background)");
			await eventually(() => registryOf().all().find((run) => run.name === "done")?.state === "failed");
			assert.equal(JSON.parse((appended.at(-1)![1] as { text: string }).text.replace(/^echo: /, "")).prompt, "Task: STUB_INSPECT");
			assert.equal(background.digest()?.match(/^\[fork done /gm)?.length, 2);
		});

		test("a warm fork gets main's latest prefix, and fork_resume with a task keeps the one it started with", async () => {
			const track = (payload: unknown) => {
				let handler: any;
				trackPrefix({ on: (_event: string, listener: unknown) => (handler = listener) } as any);
				handler({ payload });
			};
			track({ system: "first", tools: [{ name: "read" }] });
			const { tool, tools, sent, appended, ctx } = await fork({ task: "STUB_INSPECT", name: "kept" });
			assert.deepEqual(JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, "")).leadPrefix, { system: "first", tools: [{ name: "read" }] });
			track({ system: "later", tools: [{ name: "read" }] });
			await tools.fork_resume.execute("r", { name: "kept", task: "STUB_INSPECT" }, undefined, undefined, ctx);
			await eventually(() => sent.length > 0);
			assert.equal(JSON.parse((appended.at(-1)![1] as { text: string }).text.replace(/^echo: /, "")).leadPrefix.system, "first");
		});

		test("a new fork names every finished fork of the same role and directory whose cache is still warm", async () => {
			await fork({ task: "STUB_REPORT", name: "warm" });
			await fork({ task: "STUB_REPORT", name: "warmer" });
			const { tool } = await start({ task: "STUB_REPORT", name: "next" });
			assert.match(tool.content[0].text, /^started fork next \(background\)\nfork warmer: 216 ctx, cache \d+m left\nfork warm: 216 ctx, cache \d+m left\nfork_resume\(\{name, task\}\) is cheaper than a fresh fork$/);
		});

		test("the warm-fork hint stays silent when a fresh fork reads less cached context than the finished fork holds", async () => {
			await fork({ task: "STUB_REPORT", name: "big" });
			mainContext = 100;
			const { tool } = await start({ task: "STUB_REPORT", name: "next" });
			assert.equal(tool.content[0].text, "started fork next (background)");
		});

		test("the warm-fork hint prices a cold start at the selected model's rates", async () => {
			await fork({ task: "STUB_REPORT", name: "lead" });
			const cheap = await start({ task: "STUB_REPORT", name: "cheapcold", model: "prov/cheap" });
			assert.match(cheap.tool.content[0].text, /^started cold worker cheapcold on prov\/cheap \(no shared context\) \(background\)\ncheapcold starts when stub-\w+ finishes$/);
			const dear = await start({ task: "STUB_REPORT", name: "dearcold", model: "prov/dear" });
			assert.match(dear.tool.content[0].text, /\nfork lead: 216 ctx, cache \d+m left\n/);
		});

		test("the warm-fork hint prices a finished cold worker at its own model's rates", async () => {
			await fork({ task: "STUB_REPORT", name: "dearrun", model: "prov/dear" });
			const { tool } = await start({ task: "STUB_REPORT", name: "next" });
			assert.equal(tool.content[0].text, "started fork next (background)");
		});

		test("the warm-fork hint prices a finished warm fork at the model it saved, not the lead's current one", async () => {
			leadModel = "dear";
			await fork({ task: "STUB_REPORT", name: "saved" });
			leadModel = "mod";
			const { tool } = await start({ task: "STUB_REPORT", name: "next" });
			assert.equal(tool.content[0].text, "started fork next (background)");
		});

		test("the warm-fork hint skips a name whose latest finished fork, the one fork_resume picks, has a cold cache", async () => {
			await fork({ task: "STUB_REPORT", name: "dup" });
			await fork({ task: "STUB_REPORT", name: "dup" });
			registryOf().update(registryOf().all().filter((run) => run.name === "dup").at(-1)!.id, { lastRequestAt: 0 });
			const { tool } = await start({ task: "STUB_REPORT", name: "next" });
			assert.equal(tool.content[0].text, "started fork next (background)");
		});
	});

	describe("with the MCP proxy", () => {
		beforeEach(() => void (settings = PROXY_ON));

		test("starts the child without MCP servers and describes main's tools and servers section in the handshake", async () => {
			const { tool } = await fork({ task: "STUB_INSPECT" });
			const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
			assert.equal(seen.args.at(-1), "--no-mcp");
			assert.deepEqual(seen.handshake.bridge, { socket: seen.handshake.bridge.socket, activeTools: ["read", "codemode"], tools: [{ name: "mcp__semble__search", description: "d", parameters: {}, exposure: "codemode" }], section: "semble (codemode)" });
			assert.equal(seen.socketExists, true);
		});

		test("runs the child's MCP calls in main and reaches main's tool result", async () => {
			const { tool } = await fork({ task: "STUB_BRIDGE" });
			assert.match(tool.content[0].text, /^echo: ran mcp__semble__search {"query":"q"}/);
		});

		test("leaves the child's own MCP servers on when the proxy is off", async () => {
			settings = {};
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
		useEnv({ PI_CONTEXT_TEST_CMD: "true" });

		const primary = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-primary-")));
		const repo = path.join(primary, "lead");
		after(() => fs.rmSync(primary, { recursive: true }));

		test("makes its own worktree when the session is a primary checkout and no target is given", async () => {
			git(primary, "init", "-b", "main");
			git(primary, "config", "user.email", "t@example.com");
			git(primary, "config", "user.name", "t");
			git(primary, "commit", "--allow-empty", "-m", "start");
			git(primary, "worktree", "add", "-q", "-b", "lead", repo);
			const { tool, appended } = await fork({ task: "STUB_WRITE", role: "writer", name: "primary" }, primary);
			const handshake = JSON.parse((appended[0][1] as { text: string }).text.split("\n")[1]);
			assert.ok(handshake.worktree.startsWith(path.join(agentDir, "pi-context", "worktrees")));
			assert.match(tool.details.digest, /\[merge: landed [0-9a-f]{9}\]/);
			assert.equal(git(primary, "log", "-1", "--format=%s", "main"), "write");
		});

		describe("as a team", () => {
			const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-team-")));
			const lead = path.join(root, "lead");
			const handshake = path.join(root, "team-handshake.json");
			after(() => fs.rmSync(root, { recursive: true }));
			before(() => {
				git(root, "init", "-b", "main");
				git(root, "config", "user.email", "t@example.com");
				git(root, "config", "user.name", "t");
				git(root, "commit", "--allow-empty", "-m", "start");
				git(root, "worktree", "add", "-q", "-b", "lead", lead);
				fs.writeFileSync(handshake, JSON.stringify({ role: "team" }));
			});
			useEnv(() => ({ PI_CONTEXT_CHILD: handshake, PI_CONTEXT_ROLE: "team", PI_CONTEXT_WORKTREE: lead }));

			test("a writer member defaults to the team's worktree, not the directory the team's process started in, and may not work outside it", async () => {
				const { tool } = await fork({ task: "STUB_INSPECT", role: "writer", name: "mate" }, root);
				const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
				assert.equal(seen.handshake.repo, lead);
				const outside = await start({ task: "STUB_INSPECT", role: "writer", name: "stray", target: root }, root);
				assert.match(outside.tool.message, /only inside the team's worktree/);
				assert.equal(git(root, "branch", "--list", "fork/stray"), "");
			});

			test("writers forked together from one commit each land on the team's branch, even though the first landing moved it", async () => {
				const before = git(lead, "rev-parse", "HEAD");
				const started = await Promise.all(["w1", "w2"].map((name) => start({ task: "STUB_WRITE", role: "writer", name }, root)));
				const landed = await Promise.all(started.map(({ tool, appended, sent }) => settle(tool, appended, sent)));
				for (const { details } of landed) assert.match(details.unread, /\[merge: landed [0-9a-f]{9}\]/);
				assert.equal(git(lead, "rev-list", "--count", `${before}..HEAD`), "2");
			});

			test("a team's writer cannot take its own branch or base, which would push around the team's worktree", async () => {
				for (const extra of [{ branch: "feature/x" }, { branch: "feature/x", base: "main" }]) {
					const { tool } = await start({ task: "STUB_WRITE", role: "writer", name: "pusher", ...extra }, root);
					assert.match(tool.message, /branch and base are not allowed in a team/);
				}
				assert.equal(git(root, "branch", "--list", "feature/x"), "");
			});

			test("a reload that reload_now requested resumes the team's own lost members and not another session's", async () => {
				const { ctx, handlers } = await start({ task: "STUB_INSPECT", name: "unused" }, root);
				const files = fs.mkdtempSync(path.join(agentDir, "reload-"));
				const previous = process.env.PI_CONTEXT_RUN_ID;
				process.env.PI_CONTEXT_RUN_ID = "team1";
				const lost = { role: "reader", background: true, state: "lost", task: "t", files, startedAt: 1, endedBy: "reload", queued: { message: "again", resume: false } } satisfies Omit<Run, "id" | "name">;
				registryOf().start({ ...lost, id: "mine1", name: "mine" });
				registryOf().start({ ...lost, id: "theirs1", name: "theirs" });
				registryOf().update("theirs1", { owner: "other" });
				const requested = Symbol.for("llm-prompts.reload-now.requested");
				(globalThis as any)[requested] = true;
				try {
					await handlers.session_start({ reason: "reload" }, ctx);
				} finally {
					delete (globalThis as any)[requested];
					if (previous === undefined) delete process.env.PI_CONTEXT_RUN_ID;
					else process.env.PI_CONTEXT_RUN_ID = previous;
				}
				assert.equal(registryOf().get("mine1")?.state, "running");
				assert.equal(registryOf().get("theirs1")?.state, "lost");
			});

			test("a team cannot resume or continue a team", async () => {
				const files = fs.mkdtempSync(path.join(agentDir, "nested-"));
				fs.writeFileSync(path.join(files, "seed.jsonl"), "{}\n");
				registryOf().start({ id: "nested1", name: "nested", role: "team", background: true, state: "done", task: "t", files, startedAt: 1 });
				const { tools, ctx } = await start({ task: "STUB_INSPECT", name: "unused" }, root);
				await assert.rejects(tools.fork_resume.execute("c", { name: "nested", task: "again" }, undefined, undefined, ctx), /A team cannot start a team/);
			});
		});

		test("a team gets its own worktree and main's MCP bridge without the mcpProxy setting", async () => {
			const { tool } = await fork({ task: "STUB_INSPECT", role: "team", name: "crew" }, repo);
			const seen = JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, ""));
			assert.equal(seen.handshake.role, "team");
			assert.match(seen.handshake.worktree, /\/crew$/);
			assert.ok(seen.handshake.bridge.socket);
			assert.ok(seen.args.includes("--no-mcp"));
		});

		test("a writer from a reader that ran in a primary checkout makes its own worktree", async () => {
			await fork({ task: "STUB_REPORT", name: "psrc" }, primary);
			const { tool, appended } = await fork({ task: "STUB_WRITE", role: "writer", name: "pkid", from: "psrc" }, repo);
			const handshake = JSON.parse((appended[0][1] as { text: string }).text.split("\n")[1]);
			assert.ok(handshake.worktree.startsWith(path.join(agentDir, "pi-context", "worktrees")));
			assert.match(JSON.stringify(tool.details), /\[merge: landed [0-9a-f]{9}\]/);
		});

		test("a large writer cancelled while its summary is written makes no worktree", async () => {
			let written!: (summary: string) => void;
			const { tools, ctx } = await start({ task: "STUB_WRITE", role: "writer", name: "bigw" }, repo, undefined, undefined, WARM_FORK_MAX_TOKENS + 1, () => new Promise<string>((resolve) => (written = resolve)));
			await tools.fork_cancel.execute("c", { name: "bigw" }, undefined, undefined, ctx);
			written("LATE");
			await new Promise((resolve) => setTimeout(resolve, 200));
			assert.equal(git(repo, "branch", "--list", "fork/bigw"), "");
		});

		test("fork_resume with a task continues a cancelled writer in its kept worktree, with its session", async () => {
			const life = path.join(agentDir, "life.log");
			const { tools, appended, ctx } = await start({ task: `STUB_STEER STUB_LIFE:${life}`, role: "writer", name: "stopped" }, repo);
			const run = () => registryOf().all().find((candidate) => candidate.name === "stopped")!;
			await eventually(() => fs.existsSync(life));
			const { worktree, files } = run();
			await tools.fork_cancel.execute("c", { name: "stopped" }, undefined, undefined, ctx);
			assert.equal((await tools.fork_resume.execute("r", { name: "stopped", task: `STUB_INSPECT STUB_LIFE:${life}` }, undefined, undefined, ctx)).content[0].text, "continued fork stopped (background)");
			await eventually(() => appended.length > 0);
			const seen = JSON.parse((appended.at(-1)![1] as { text: string }).text.split("\n")[0].replace(/^echo: /, ""));
			assert.equal(seen.handshake.worktree, worktree);
			assert.equal(seen.args[seen.args.indexOf("--session") + 1], path.join(files!, "seed.jsonl"));
			await eventually(() => !isLive(run()));
			assert.equal(fs.readFileSync(life, "utf8"), "prompt\nexit\nprompt\nexit\n");
		});

		test("a second fork_resume on a cancelled fork while it stops queues its task instead of starting the fork again", async () => {
			const life = path.join(agentDir, "twice.log");
			const { tools, ctx } = await start({ task: `STUB_STEER STUB_LIFE:${life}`, role: "writer", name: "twice" }, repo);
			await eventually(() => fs.existsSync(life));
			await tools.fork_cancel.execute("c", { name: "twice" }, undefined, undefined, ctx);
			const resumes = await Promise.allSettled(["r1", "r2"].map((id) => tools.fork_resume.execute(id, { name: "twice", task: `STUB_LIFE:${life}` }, undefined, undefined, ctx)));
			assert.deepEqual(
				resumes.map((resume) => resume.status === "fulfilled" && resume.value.content[0].text),
				["continued fork twice (background)", `queued for fork twice (background): STUB_LIFE:${life} starts after it replies`],
			);
			await eventually(() => !isLive(registryOf().all().find((candidate) => candidate.name === "twice")!));
			assert.equal(fs.readFileSync(life, "utf8"), "prompt\nexit\nprompt\nexit\n");
		});

		test("a large writer whose tool call is aborted while its summary is written makes no worktree and starts no run", async () => {
			let written!: (summary: string) => void;
			const controller = new AbortController();
			const { sent } = await start({ task: "STUB_WRITE", role: "writer", name: "bigesc" }, repo, undefined, undefined, WARM_FORK_MAX_TOKENS + 1, () => new Promise<string>((resolve) => (written = resolve)), controller.signal);
			controller.abort();
			assert.equal(registryOf().all().find((run) => run.name === "bigesc")?.state, "cancelled");
			written("LATE");
			await new Promise((resolve) => setTimeout(resolve, 200));
			assert.equal(git(repo, "branch", "--list", "fork/bigesc"), "");
			assert.deepEqual(sent, []);
		});

		test("a large writer whose tool call is already aborted registers no run", async () => {
			const { tool } = await start({ task: "STUB_WRITE", role: "writer", name: "bigpre" }, repo, undefined, undefined, WARM_FORK_MAX_TOKENS + 1, undefined, AbortSignal.abort());
			assert.ok(tool instanceof Error);
			assert.equal(registryOf().all().some((run) => run.name === "bigpre"), false);
		});

		test("a from fork whose worktree cannot be made leaves no copied session behind", async () => {
			await fork({ task: "STUB_REPORT", name: "wtsrc" }, repo);
			git(repo, "branch", "fork/wtdup");
			const runs = () => fs.readdirSync(path.join(agentDir, "pi-context")).sort();
			const before = runs();
			assert.ok((await fork({ task: "x", role: "writer", name: "wtdup", from: "wtsrc" }, repo)).tool instanceof Error);
			assert.deepEqual(runs(), before);
		});

		test("works in a worktree under the agent directory and lands its commits on the main checkout", async () => {
			const { tool, appended } = await fork({ task: "STUB_WRITE", role: "writer", name: "w" }, repo);
			const handshake = JSON.parse((appended[0][1] as { text: string }).text.split("\n")[1]);
			assert.equal(handshake.role, "writer");
			assert.match((appended[0][1] as { text: string }).text, new RegExp(`Your worktree: ${handshake.worktree}`));
			assert.ok(handshake.worktree.startsWith(path.join(agentDir, "pi-context", "worktrees")));
			assert.match((appended[0][1] as { text: string }).text, new RegExp(`worktreeEnv ${handshake.worktree}$`, "m"));
			assert.match(tool.details.digest, /\[merge: landed [0-9a-f]{9}\]/);
			assert.equal(fs.readFileSync(path.join(repo, fs.readdirSync(repo).find((file) => file.startsWith("written-"))!), "utf8"), "from the fork");
			assert.equal(fs.existsSync(handshake.worktree), false);
		});

		test("does not land the commits of a reply without an OUTCOME line", async () => {
			const before = git(repo, "rev-parse", "HEAD");
			const { tool } = await fork({ task: "STUB_WRITE STUB_NO_OUTCOME", role: "writer", name: "nooutcome" }, repo);
			assert.doesNotMatch(tool.details.digest, /\[merge: landed/);
			assert.equal(git(repo, "rev-parse", "HEAD"), before);
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
			assert.ok((appended[0][1] as { text: string }).text.includes(`Your commits land on fork/elsewhere in ${other} when you finish. Do not name ${other} or other worktrees in commands.`));
			assert.match(tool.details.digest, /\[merge: landed [0-9a-f]{9}\]/);
			assert.equal(git(other, "log", "-1", "--format=%s", "trunk"), "write");
			assert.equal(git(repo, "rev-parse", "HEAD"), before);
			assert.equal(git(repo, "status", "--porcelain"), "");
		});

		test("a writer with an unknown tier fails before it creates a worktree", async () => {
			const { tool } = await fork({ task: "STUB_WRITE", role: "writer", name: "badtier", model: "nosuch" }, repo);
			assert.match(String(tool), /unknown model tier nosuch/);
			assert.equal(forkDirs().some((dir) => String(dir).includes("badtier")), false);
		});

		test("a writer that switches branch keeps its worktree, with a short digest phrase and the full reason in the stored result", async () => {
			const { tool, appended } = await fork({ task: "STUB_SWITCH", role: "writer", name: "switcher" }, repo);
			assert.match(tool.details.digest, /\[merge: kept worktree: fork switched branch\]/);
			assert.doesNotMatch(tool.details.digest, /worktrees\//);
			const stored = (appended.find(([type]) => type === "result-cap")?.[1] as { text: string }).text;
			assert.match(stored, /escalated: the worktree left fork\/switcher for refs\/heads\/elsewhere\nworktree kept at \S+switcher on branch fork\/switcher/);
		});

		test("a cold writer starts in its worktree and lands through the same queue", async () => {
			const { tool, appended } = await fork({ task: "STUB_WRITE", role: "writer", name: "cold", model: "prov/cheap" }, repo);
			const text = (appended.find(([, entry]) => (entry as { ref: string }).ref === "rc-fork-cold-call-id")![1] as { text: string }).text;
			assert.equal(text.split("\ncwd ")[1], JSON.parse(text.split("\n")[1]).worktree);
			assert.match(tool.details.digest, /\[merge: landed [0-9a-f]{9}\]/);
		});

		test("a reader with a target inside a checkout starts in that directory, not the checkout root", async () => {
			const sub = path.join(repo, "sub");
			fs.mkdirSync(sub, { recursive: true });
			const { tool } = await fork({ task: "STUB_INSPECT", name: "subdir", target: "sub" }, repo);
			assert.equal(JSON.parse(tool.content[0].text.split("\n")[0].replace(/^echo: /, "")).cwd, sub);
		});

		test("with a target that is not a git checkout writes in place there and reports its outcome without landing", async () => {
			const plain = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-plain-")));
			after(() => fs.rmSync(plain, { recursive: true }));
			const { tool } = await fork({ task: "STUB_INSPECT", role: "writer", name: "plain", target: plain }, repo);
			const seen = JSON.parse(tool.content[0].text.split("\n")[0]);
			assert.equal(seen.cwd, plain);
			assert.deepEqual([seen.handshake.worktree, seen.handshake.repo], [plain, undefined]);
			assert.match(seen.prompt, new RegExp(`${plain} is not a git checkout, so you have no worktree: write in place there\\. Nothing lands\\.\nTask: STUB_INSPECT$`));
			assert.equal(tool.details.merge, undefined);
			assert.doesNotMatch(tool.details.digest, /\[merge:/);
		});

		test("a failure before the child starts removes the clean worktree and its branch", async () => {
			settings = PROXY_ON;
			const failed = (await fork({ task: "hi", role: "writer", name: "early" }, repo, { activeTools: [], allTools: undefined as never })).tool;
			assert.match(failed.details.digest, /^\[fork early failed\][\s\S]*\[merge: worktree removed: clean\]/);
			assert.equal(execFileSync("git", ["-C", repo, "branch", "--list", "fork/early"], { encoding: "utf8" }), "");
		});
	});
});
