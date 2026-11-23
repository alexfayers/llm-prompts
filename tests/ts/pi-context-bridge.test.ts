import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { after, describe, mock, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { connectBridge, describeMain, prefixHash, reportPrefixToFile, serveBridge, trackPrefix, writeLeadPrefix } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/bridge.ts";
import { ROLES, withReadMcp } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/roles.ts";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-bridge-"));
after(() => fs.rmSync(dir, { recursive: true }));

const reply = (text: string) => ({ content: [{ type: "text", text }], details: { text }, isError: false });

describe("bridge", () => {
	test("a call in the child runs the tool in main and returns its result", async () => {
		const calls: unknown[][] = [];
		const server = await serveBridge(dir, { role: ROLES.reader, execute: async (tool, args) => (calls.push([tool, args]), reply("found")) });
		const client = await connectBridge(server.socket);
		const result = await client.call("mcp__semble__search", { query: "q" });
		client.close();
		await server.close();
		assert.deepEqual(calls, [["mcp__semble__search", { query: "q" }]]);
		assert.equal(result.content[0].text, "found");
		assert.equal(fs.existsSync(server.socket), false);
	});

	test("a tool the role may not use is refused without running", async () => {
		let ran = 0;
		const server = await serveBridge(dir, { role: ROLES.reader, execute: async () => (ran++, reply("x")) });
		const client = await connectBridge(server.socket);
		await assert.rejects(client.call("mcp__memory__create_entities", {}), /role reader may not use mcp__memory__create_entities/);
		await assert.rejects(client.call("bash", { command: "true" }), /bash is not an MCP tool/);
		client.close();
		await server.close();
		assert.equal(ran, 0);
	});

	test("a readMcp tool runs only with matching arguments", async () => {
		const calls: unknown[] = [];
		const server = await serveBridge(dir, { role: withReadMcp(ROLES.reader, [{ tool: "mcp__demo__exec", argsMatch: { command: "read .*" } }]), execute: async (_tool, args) => (calls.push(args), reply("x")) });
		const client = await connectBridge(server.socket);
		await client.call("mcp__demo__exec", { command: "read x" });
		await assert.rejects(client.call("mcp__demo__exec", { command: "write x" }), /llmPrompts\.forks\.readMcp/);
		client.close();
		await server.close();
		assert.deepEqual(calls, [{ command: "read x" }]);
	});

	test("concurrent calls each get their own reply and a failure reaches only its caller", async () => {
		const server = await serveBridge(dir, {
			role: ROLES.reader,
			execute: async (tool, args) => {
				const { n } = args as { n: number };
				await new Promise((resolve) => setTimeout(resolve, (4 - n) * 10));
				if (n === 2) throw new Error("server down");
				return reply(`${tool}:${n}`);
			},
		});
		const client = await connectBridge(server.socket);
		const settled = await Promise.allSettled([0, 1, 2, 3].map((n) => client.call("mcp__semble__search", { n })));
		client.close();
		await server.close();
		assert.deepEqual(settled.map((outcome) => (outcome.status === "fulfilled" ? outcome.value.content[0].text : (outcome.reason as Error).message)), ["mcp__semble__search:0", "mcp__semble__search:1", "server down", "mcp__semble__search:3"]);
	});

	test("the child reports its prefix hash to main", async () => {
		const seen: string[] = [];
		const server = await serveBridge(dir, { role: ROLES.reader, execute: async () => reply("x"), onPrefix: (hash) => seen.push(hash) });
		const client = await connectBridge(server.socket);
		client.report("abc");
		await client.call("mcp__semble__search", {});
		client.close();
		await server.close();
		assert.deepEqual(seen, ["abc"]);
	});

	test("a server error after listening does not crash the process", async () => {
		const created = mock.method(net, "createServer");
		const server = await serveBridge(dir, { role: ROLES.reader, execute: async () => reply("x") });
		const listening = created.mock.calls[0].result as net.Server;
		created.mock.restore();
		assert.doesNotThrow(() => listening.emit("error", new Error("EMFILE")));
		await server.close();
	});
});

describe("prefixHash", () => {
	test("ignores the messages and follows the system prompt and tools of either payload shape", () => {
		const base = { system: [{ text: "s" }], toolConfig: { tools: [{ name: "a" }] }, messages: [1] };
		assert.equal(prefixHash(base), prefixHash({ ...base, messages: [1, 2, 3] }));
		assert.notEqual(prefixHash(base), prefixHash({ ...base, system: [{ text: "t" }] }));
		assert.notEqual(prefixHash(base), prefixHash({ ...base, toolConfig: { tools: [{ name: "b" }] } }));
		assert.notEqual(prefixHash({ system: "s", tools: [{ name: "a" }] }), prefixHash({ system: "s", tools: [] }));
	});
});

describe("reportPrefixToFile", () => {
	test("a delegate with its own MCP servers writes its first request's prefix hash next to the handshake", async () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-prefix-"));
		let handler: any;
		reportPrefixToFile({ on: (_event: string, listener: unknown) => (handler = listener) } as any, path.join(dir, "handshake.json"));
		handler({ payload: { system: "s", tools: [] } });
		handler({ payload: { system: "later", tools: [] } });
		assert.equal(fs.readFileSync(path.join(dir, "prefix"), "utf8"), prefixHash({ system: "s", tools: [] }));
		fs.rmSync(dir, { recursive: true });
	});
});

describe("a warm fork's first request", () => {
	const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-lead-prefix-"));
	after(() => fs.rmSync(scratch, { recursive: true }));
	const handshake = path.join(scratch, "handshake.json");
	useEnv(() => ({ PI_CONTEXT_CHILD: handshake }));
	const lead = { system: [{ type: "text", text: "rules as main loaded them" }], tools: [{ name: "read", description: "Read a file" }, { name: "bash", description: "Run" }], messages: [1] };

	async function forkRequest(payload: Record<string, unknown>, ...mainLater: Record<string, unknown>[]) {
		let track: any;
		trackPrefix({ on: (_event: string, listener: unknown) => (track = listener) } as any);
		for (const main of [lead, ...mainLater]) track({ payload: main });
		fs.rmSync(path.join(scratch, "lead-prefix.json"), { force: true });
		writeLeadPrefix(scratch);
		fs.writeFileSync(handshake, JSON.stringify({ role: "reader", inherited: "r1" }));
		return (await loadExtension("pi-context/index")).fire("before_provider_request", { payload });
	}
	const reinstalled = { system: [{ type: "text", text: "rules reinstalled since" }], tools: [{ name: "bash", description: "Run a command" }, { name: "read", description: "Read" }], messages: [1, 2] };

	test("sends main's system prompt and tools byte for byte, with its own messages", async () => {
		const sent = await forkRequest({ system: [{ type: "text", text: "rules reinstalled since" }], tools: [{ name: "bash", description: "Run a command" }, { name: "read", description: "Read" }], messages: [1, 2] });
		assert.equal(prefixHash(sent), prefixHash(lead));
		assert.deepEqual(sent.messages, [1, 2]);
	});

	test("sends main's prompt cache key in place of its own", async () => {
		let track: any;
		trackPrefix({ on: (_event: string, listener: unknown) => (track = listener) } as any);
		track({ payload: { ...lead, prompt_cache_key: "main-session" } });
		fs.rmSync(path.join(scratch, "lead-prefix.json"), { force: true });
		writeLeadPrefix(scratch);
		fs.writeFileSync(handshake, JSON.stringify({ role: "reader", inherited: "r1" }));
		const sent = await (await loadExtension("pi-context/index")).fire("before_provider_request", { payload: { ...reinstalled, prompt_cache_key: "fork-session" } });
		assert.equal(sent.prompt_cache_key, "main-session");
		assert.deepEqual(sent.messages, [1, 2]);
	});

	test("adds no prompt cache key to a request without one", async () => {
		assert.equal("prompt_cache_key" in (await forkRequest(reinstalled)), false);
	});

	test("keeps its own prefix when its tools are not main's", async () => {
		const own = { system: "s", tools: [{ name: "read" }], messages: [] };
		assert.equal(await forkRequest(own), undefined);
	});

	test("keeps its own prefix when a tool of the same name takes other parameters", async () => {
		const own = { ...reinstalled, tools: [{ name: "bash", input_schema: { type: "object", properties: { cmd: {} } } }, { name: "read" }] };
		assert.equal(await forkRequest(own), undefined);
	});

	test("ignores main's requests without tools, such as a compaction summary", async () => {
		const sent = await forkRequest(reinstalled, { system: "Summarize the conversation", messages: [] });
		assert.equal(prefixHash(sent), prefixHash(lead));
	});

	test("reports main's prefix hash once it sent main's prefix", async () => {
		fs.rmSync(path.join(scratch, "prefix"), { force: true });
		await forkRequest(reinstalled);
		assert.equal(fs.readFileSync(path.join(scratch, "prefix"), "utf8"), prefixHash(lead));
	});

	test("without main's prefix file, sends its own payload unchanged", async () => {
		fs.rmSync(path.join(scratch, "lead-prefix.json"), { force: true });
		fs.writeFileSync(handshake, JSON.stringify({ role: "reader", inherited: "r1" }));
		assert.equal(await (await loadExtension("pi-context/index")).fire("before_provider_request", { payload: reinstalled }), undefined);
	});
});

describe("describeMain", () => {
	test("lists main's active tools, its MCP tools and the rendered MCP servers section", () => {
		const mcp = { name: "mcp__semble__search", description: "d", parameters: { type: "object" }, exposure: "codemode", namespace: { name: "mcp__semble" }, annotations: { readOnlyHint: true }, sourceInfo: {}, reachesTools: undefined };
		const other = { name: "read", description: "r", parameters: {}, exposure: "direct", sourceInfo: {} };
		const resource = { ...mcp, name: "read_mcp_resource" };
		const pi = { getActiveTools: () => ["read", "codemode"], getAllTools: () => [other, mcp, resource] } as any;
		const ctx = { getSystemPrompt: () => "intro\n<mcp_servers>\nMCP servers whose tools are not declared to you.\n- semble (codemode)\n</mcp_servers>\n<other>x</other>" } as any;
		assert.deepEqual(describeMain(pi, ctx), {
			activeTools: ["read", "codemode"],
			tools: [
				{ name: "mcp__semble__search", description: "d", parameters: { type: "object" }, exposure: "codemode", namespace: { name: "mcp__semble" }, annotations: { readOnlyHint: true } },
				{ name: "read_mcp_resource", description: "d", parameters: { type: "object" }, exposure: "codemode", namespace: { name: "mcp__semble" }, annotations: { readOnlyHint: true } },
			],
			section: "MCP servers whose tools are not declared to you.\n- semble (codemode)",
		});
		assert.equal(describeMain(pi, { getSystemPrompt: () => "no section" } as any).section, undefined);
	});

	test("gives a role its own tools even when main turned them off", () => {
		const tool = (name: string) => ({ name, description: name, parameters: {}, exposure: "direct", sourceInfo: {} });
		const pi = { getActiveTools: () => ["read", "codemode"], getAllTools: () => ["read", "bash", "edit", "write", "codemode"].map(tool) } as any;
		const ctx = { getSystemPrompt: () => "" } as any;
		assert.deepEqual(describeMain(pi, ctx, ROLES.writer).activeTools.sort(), ["bash", "codemode", "edit", "read", "write"]);
		assert.deepEqual(describeMain(pi, ctx, ROLES.reader).activeTools.sort(), ["bash", "codemode", "read"]);
	});
});

describe("a delegate started with the bridge", () => {
	const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-bridge-child-"));
	after(() => fs.rmSync(scratch, { recursive: true }));
	const handshake = path.join(scratch, "handshake.json");
	useEnv(() => ({ PI_CONTEXT_CHILD: handshake }));

	async function child(execute: (tool: string, args: unknown) => Promise<ReturnType<typeof reply>>) {
		const prefixes: string[] = [];
		let reportReceived = () => {};
		const reported = new Promise<void>((resolve) => (reportReceived = resolve));
		const server = await serveBridge(scratch, { role: ROLES.reader, execute, onPrefix: (hash) => (prefixes.push(hash), reportReceived()) });
		const tool = { name: "mcp__semble__search", description: "Search code", parameters: { type: "object" }, exposure: "codemode", namespace: { name: "mcp__semble" }, annotations: { readOnlyHint: true } };
		const bridge = { socket: server.socket, activeTools: ["read", "codemode"], tools: [tool], section: "MCP servers: semble" };
		fs.writeFileSync(handshake, JSON.stringify({ role: "reader", bridge }));
		return { loaded: await loadExtension("pi-context/index"), server, prefixes, reported, tool };
	}

	test("registers main's MCP tools as proxies that run in main, and fails like the tool did", async () => {
		const { loaded, server, tool } = await child(async (name, args) => reply(`${name} ${JSON.stringify(args)}`));
		const proxy = loaded.tools[tool.name];
		assert.deepEqual({ exposure: proxy.exposure, namespace: proxy.namespace, description: proxy.description, annotations: proxy.annotations }, { exposure: "codemode", namespace: tool.namespace, description: "Search code", annotations: tool.annotations });
		const result = await proxy.execute("id", { query: "q" });
		assert.equal(result.content[0].text, 'mcp__semble__search {"query":"q"}');
		await server.close();
	});

	test("an error result of the tool in main throws in the proxy", async () => {
		const { loaded, server, tool } = await child(async () => ({ ...reply("boom"), isError: true }));
		await assert.rejects(loaded.tools[tool.name].execute("id", {}), /boom/);
		await server.close();
	});

	test("declares main's tools and MCP servers section, and reports the first request's prefix", async () => {
		const { loaded, server, prefixes, reported } = await child(async () => reply("x"));
		await loaded.fire("session_start", { reason: "startup" });
		assert.deepEqual(loaded.pi.activeTools, ["read", "codemode"]);
		const sections: Record<string, string> = {};
		await loaded.fire("before_agent_start", { systemPromptOptions: { sections, contextFiles: [] } });
		assert.equal(sections.mcp_servers, "MCP servers: semble");
		const payload = { system: "s", tools: [] };
		await loaded.fire("before_provider_request", { payload });
		await loaded.fire("before_provider_request", { payload: { system: "later", tools: [] } });
		await reported;
		await server.close();
		assert.deepEqual(prefixes, [prefixHash(payload)]);
	});
});
