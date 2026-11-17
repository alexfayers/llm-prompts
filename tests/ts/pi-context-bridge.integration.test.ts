// Real-model check that a fork with the MCP proxy starts no MCP server of its own. Runs only with PI_CONTEXT_INTEGRATION=1 and PI_CONTEXT_AGENT_DIR set to a scratch agent directory.
// Env: PI_CONTEXT_PI (the pi command, default pi), PI_CONTEXT_MODEL (default haiku)
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { RpcChild } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/runner.ts";

const MODEL = process.env.PI_CONTEXT_MODEL ?? "haiku";
const SERVER = path.join(import.meta.dirname, "fixtures/mcp-counter.mjs");
const TASK = "Run a codemode script that calls `await tools.mcp__semble__ping({})` and returns its result, then reply with the line `OUTCOME done ref:x` followed by the result text.";
const entriesOf = (dir: string) => fs.readdirSync(dir, { recursive: true, encoding: "utf8" }).filter((file) => file.endsWith(".jsonl")).flatMap((file) => fs.readFileSync(path.join(dir, file), "utf8").trim().split("\n").map((line) => JSON.parse(line)));

async function runFork(agentDir: string, proxy: boolean) {
	const work = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-bridge-it-"));
	const spawnLog = path.join(work, "spawns");
	fs.writeFileSync(spawnLog, "");
	const settingsFile = path.join(agentDir, "settings.json");
	const settings = fs.existsSync(settingsFile) ? JSON.parse(fs.readFileSync(settingsFile, "utf8")) : {};
	fs.writeFileSync(settingsFile, JSON.stringify({ ...settings, llmPrompts: { ...settings.llmPrompts, forks: { ...settings.llmPrompts?.forks, mcpProxy: proxy } } }));
	fs.writeFileSync(path.join(agentDir, "mcp.json"), JSON.stringify({ mcpServers: { semble: { type: "stdio", command: process.execPath, args: [SERVER], env: { MCP_SPAWN_LOG: spawnLog }, description: "Test server with a ping tool" } } }));
	const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(PI|HERDR)_/.test(key)));
	const main = RpcChild.start({
		command: [process.env.PI_CONTEXT_PI ?? "pi"],
		args: ["--mode", "rpc", "--session-dir", path.join(work, "sessions"), "--model", MODEL, "--thinking", "off"],
		cwd: work,
		env: { ...env, PI_CODING_AGENT_DIR: agentDir, PI_CACHE_RETENTION: "long", PI_SKIP_VERSION_CHECK: "1" },
		onUi: (request) => (request.method === "confirm" ? { confirmed: true } : request.method === "select" ? { value: (request.options as string[])[0] } : undefined),
	});
	try {
		assert.equal((await main.prompt("Reply with the single word ready.")).error, undefined);
		assert.equal((await main.prompt(`Call the fork tool once with the task: ${TASK} Then reply with the word finished.`)).error, undefined);
	} finally {
		await main.close();
	}
	const entries = entriesOf(path.join(work, "sessions"));
	const forkResult = entries.find((entry) => entry.message?.toolName === "fork");
	assert.ok(forkResult, "main called the fork tool");
	const reply = entries.find((entry) => entry.customType === "result-cap" && entry.data?.ref === `rc-fork-${forkResult.message.details.name}`);
	return { spawns: fs.readFileSync(spawnLog, "utf8").trim().split("\n").filter(Boolean).length, result: forkResult.message, reply: reply?.data.text as string };
}

test("a fork with the MCP proxy reaches main's MCP server without starting its own", { skip: !process.env.PI_CONTEXT_INTEGRATION, timeout: 600_000 }, async (t) => {
	const agentDir = process.env.PI_CONTEXT_AGENT_DIR;
	assert.ok(agentDir && path.resolve(agentDir) !== path.join(os.homedir(), ".pi", "agent"), "PI_CONTEXT_AGENT_DIR must name a scratch agent directory");
	const own = await runFork(agentDir, false);
	const proxied = await runFork(agentDir, true);
	for (const [label, run] of [["own MCP", own], ["proxy", proxied]] as const) t.diagnostic(`${label}: spawns ${run.spawns}, prefix ${run.result.details?.prefix}, first usage ${JSON.stringify(run.result.details?.firstUsage)}, result ${JSON.stringify(run.result.content)}`);
	assert.equal(own.spawns, 2);
	assert.equal(proxied.spawns, 1);
	assert.match(proxied.reply, /pong/);
	assert.equal(proxied.result.details.prefix, "match");
});
