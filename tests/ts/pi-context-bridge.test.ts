import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { after, describe, mock, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { connectBridge, describeMain, prefixHash, serveBridge } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/bridge.ts";
import { ROLES } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/roles.ts";

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
		await loaded.fire("before_agent_start", { systemPromptOptions: { sections } });
		assert.equal(sections.mcp_servers, "MCP servers: semble");
		const payload = { system: "s", tools: [] };
		await loaded.fire("before_provider_request", { payload });
		await loaded.fire("before_provider_request", { payload: { system: "later", tools: [] } });
		await reported;
		await server.close();
		assert.deepEqual(prefixes, [prefixHash(payload)]);
	});
});
