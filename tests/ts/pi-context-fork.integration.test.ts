// Real-model check that a fork reuses its parent's prompt cache. Runs only with PI_CONTEXT_INTEGRATION=1 and PI_CONTEXT_AGENT_DIR set to a scratch agent directory.
// Env: PI_CONTEXT_PI (the pi command, default pi), PI_CONTEXT_MODEL (required), PI_CONTEXT_MIN_CACHE_RATIO (default 0.9)
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { integrationModel } from "./helpers.ts";
import { RpcChild } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/runner.ts";

const MIN_RATIO = Number(process.env.PI_CONTEXT_MIN_CACHE_RATIO ?? 0.9);
const FORK_TASK = "Reply with the line `OUTCOME done ref:x` and then the word ok.";
const entriesOf = (dir: string) => fs.readdirSync(dir, { recursive: true, encoding: "utf8" }).filter((file) => file.endsWith(".jsonl")).flatMap((file) => fs.readFileSync(path.join(dir, file), "utf8").trim().split("\n").map((line) => JSON.parse(line)));
const requestTokens = (usage: Record<string, number>) => usage.input + usage.cacheRead + usage.cacheWrite;

test("a fork's first request reads the parent's cached prefix", { skip: !process.env.PI_CONTEXT_INTEGRATION, timeout: 300_000 }, async (t) => {
	const agentDir = process.env.PI_CONTEXT_AGENT_DIR;
	assert.ok(agentDir && path.resolve(agentDir) !== path.join(os.homedir(), ".pi", "agent"), "PI_CONTEXT_AGENT_DIR must name a scratch agent directory");
	const work = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-fork-it-"));
	const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(PI|HERDR)_/.test(key)));
	const main = RpcChild.start({
		command: [process.env.PI_CONTEXT_PI ?? "pi"],
		args: ["--mode", "rpc", "--session-dir", path.join(work, "sessions"), "--model", integrationModel(), "--thinking", "off"],
		cwd: work,
		env: { ...env, PI_CODING_AGENT_DIR: agentDir, PI_CACHE_RETENTION: "long", PI_SKIP_VERSION_CHECK: "1" },
		onUi: (request) => (request.method === "confirm" ? { confirmed: true } : request.method === "select" ? { value: (request.options as string[])[0] } : undefined),
	});
	try {
		assert.equal((await main.prompt("Reply with the single word ready.")).error, undefined);
		const turn = await main.prompt(`Call the fork tool once with the task: ${FORK_TASK} Then reply with the word finished.`);
		assert.equal(turn.error, undefined);
	} finally {
		await main.close();
	}
	const mainEntries = entriesOf(path.join(work, "sessions"));
	const forkResult = mainEntries.find((entry) => entry.message?.toolName === "fork");
	assert.ok(forkResult, "main called the fork tool");
	const parent = mainEntries.filter((entry) => entry.message?.role === "assistant").map((entry) => entry.message.usage);
	const first = forkResult.message.details.firstUsage;
	const ratio = first.cacheRead / requestTokens(first);
	t.diagnostic(`parent requests: ${JSON.stringify(parent)}`);
	t.diagnostic(`fork first request: ${JSON.stringify(first)} cache read ratio ${ratio.toFixed(4)}`);
	const seedFile = fs.readdirSync(path.join(agentDir, "pi-context"), { recursive: true, encoding: "utf8" }).find((file) => file.endsWith("seed.jsonl"));
	const forkEntries = fs.readFileSync(path.join(agentDir, "pi-context", seedFile!), "utf8").trim().split("\n").map((line) => JSON.parse(line));
	const own = forkEntries.filter((entry) => !mainEntries.some((other) => other.id === entry.id));
	t.diagnostic(`entries added by the fork: ${own.map((entry) => `${entry.type}:${entry.customType ?? entry.message?.role ?? ""}`).join(" ")}`);
	assert.ok(ratio >= MIN_RATIO, `first request cache read ratio ${ratio}`);
});
