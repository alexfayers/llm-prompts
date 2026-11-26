import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import { copySession, coldArgs } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/fork.ts";
import { coldCard, ROLES } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/roles.ts";
import { sessionFileOf } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";
import { RpcChild } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/runner.ts";

const ROOT = path.resolve(import.meta.dirname, "../..");
const PI = path.join(ROOT, "node_modules/.bin/pi");
const EXTENSION = path.join(ROOT, "src/llm_prompts/prompts/pi/extensions/pi-context/index.ts");

type Request = { messages: { role: string; content: unknown }[]; tools?: unknown };
const requests: Request[] = [];
const server = http.createServer((request, response) => {
	let body = "";
	request.on("data", (chunk) => (body += chunk));
	request.on("end", () => {
		requests.push(JSON.parse(body));
		response.writeHead(400, { "content-type": "application/json" }).end(JSON.stringify({ error: { message: "stop" } }));
	});
});
before(() => new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve)));
after(() => server.close());

const prefixOf = ({ messages, tools }: Request) => ({ system: messages.filter(({ role }) => role === "system" || role === "developer"), tools });

test("a stub and a child that continues its session send the same system prompt and tools, also when the agent dir gains an entry between them", { timeout: 120_000 }, async () => {
	const work = fs.mkdtempSync(path.join(os.tmpdir(), "stub-prompt-"));
	const agentDir = path.join(work, "agent");
	fs.mkdirSync(agentDir);
	fs.writeFileSync(path.join(agentDir, "AGENTS.md"), "main rules");
	fs.writeFileSync(path.join(agentDir, "AGENTS.delegate.md"), "delegate rules");
	const { port } = server.address() as { port: number };
	fs.writeFileSync(path.join(agentDir, "models.json"), JSON.stringify({ providers: { stub: { baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: "x", api: "openai-completions", models: [{ id: "m" }] } } }));
	const cwd = path.join(work, "cwd");
	fs.mkdirSync(cwd);
	const role = ROLES.reader;
	const run = async (files: string, session: string | undefined, message: string) => {
		fs.mkdirSync(files, { recursive: true });
		fs.writeFileSync(path.join(files, "card.md"), coldCard(role));
		const handshake = path.join(files, "handshake.json");
		if (!fs.existsSync(handshake)) fs.writeFileSync(handshake, JSON.stringify({ role: role.name }));
		const child = RpcChild.start({
			command: [PI],
			cwd,
			args: [...coldArgs(role, { model: "stub/m", sessionDir: path.join(files, "session"), cardFile: path.join(files, "card.md"), skillsDir: path.join(agentDir, "skills"), session }), "-e", EXTENSION],
			env: { ...process.env, PI_CODING_AGENT_DIR: agentDir, PI_CONTEXT_CHILD: handshake, PI_CONTEXT_ROLE: role.name, PI_SKIP_VERSION_CHECK: "1", PI_OFFLINE: "1" },
		});
		try { await child.prompt(message); } finally { await child.close(); }
	};

	const stubFiles = path.join(work, "stub");
	await run(stubFiles, undefined, "shared text");
	fs.mkdirSync(path.join(agentDir, "sessions", "pi-context"), { recursive: true });
	fs.writeFileSync(path.join(agentDir, "sessions", "pi-context", "stub.jsonl"), "");
	const childFiles = path.join(work, "child");
	copySession(stubFiles, childFiles, true);
	await run(childFiles, sessionFileOf(childFiles, true), "Task: go");

	assert.equal(requests.length, 2);
	assert.match(JSON.stringify(prefixOf(requests[0])), /delegate rules[\s\S]*"reply"/);
	assert.deepEqual(prefixOf(requests[1]), prefixOf(requests[0]));
});
