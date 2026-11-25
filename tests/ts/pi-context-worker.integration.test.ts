// Real-model check that main can run a cold worker through the fork tool. Runs only with PI_CONTEXT_INTEGRATION=1 and PI_CONTEXT_AGENT_DIR set to a scratch agent directory.
// Env: PI_CONTEXT_PI (the pi command, default pi), PI_CONTEXT_MODEL (default haiku)
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { waitForEntry } from "./helpers.ts";
import { RpcChild } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/runner.ts";

const MODEL = process.env.PI_CONTEXT_MODEL ?? "haiku";
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(PI|HERDR)_/.test(key)));

function scratchAgentDir(): string {
	const agentDir = process.env.PI_CONTEXT_AGENT_DIR;
	assert.ok(agentDir && path.resolve(agentDir) !== path.join(os.homedir(), ".pi", "agent"), "PI_CONTEXT_AGENT_DIR must name a scratch agent directory");
	fs.mkdirSync(path.join(agentDir, "extensions"), { recursive: true });
	fs.rmSync(path.join(agentDir, "extensions", "pi-context"), { force: true });
	fs.symlinkSync(path.join(import.meta.dirname, "../../src/llm_prompts/prompts/pi/extensions/pi-context"), path.join(agentDir, "extensions", "pi-context"));
	return agentDir;
}

const startPi = (agentDir: string, cwd: string, args: string[]) =>
	RpcChild.start({
		command: [process.env.PI_CONTEXT_PI ?? "pi"],
		args,
		cwd,
		env: { ...env, PI_CODING_AGENT_DIR: agentDir, PI_SKIP_VERSION_CHECK: "1" },
		onUi: (request) => (request.method === "confirm" ? { confirmed: true } : request.method === "select" ? { value: (request.options as string[])[0] } : undefined),
	});

const makeWork = (t: TestContext) => {
	const work = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-worker-it-"));
	t.after(() => fs.rmSync(work, { recursive: true }));
	return work;
};

test("main runs a cold worker through the fork tool and gets its outcome back", { skip: !process.env.PI_CONTEXT_INTEGRATION, timeout: 600_000 }, async (t) => {
	const agentDir = scratchAgentDir();
	const work = makeWork(t);
	const main = startPi(agentDir, work, ["--mode", "rpc", "--session-dir", path.join(work, "sessions"), "--model", MODEL, "--thinking", "off"]);
	const sessionEntries = () => fs.readdirSync(path.join(work, "sessions"), { recursive: true, encoding: "utf8" }).filter((file) => file.endsWith(".jsonl")).flatMap((file) => fs.readFileSync(path.join(work, "sessions", file), "utf8").trim().split("\n").map((line) => JSON.parse(line)));
	try {
		const turn = await main.prompt(`Call the fork tool once with model ${MODEL} and the task: Reply with the line \`OUTCOME done ref:x\` followed by the word hello. Then reply with the word finished.`);
		assert.equal(turn.error, undefined);
		await waitForEntry(sessionEntries, (entry) => entry.customType === "pi-context-results");
	} finally {
		await main.close();
	}
	const entries = sessionEntries();
	const forkResult = entries.find((entry) => entry.message?.toolName === "fork");
	assert.ok(forkResult, "main called the fork tool");
	t.diagnostic(`fork result: ${JSON.stringify(forkResult.message.content)}`);
	const completion = entries.find((entry) => entry.customType === "pi-context-results");
	assert.match(String(completion.content), new RegExp(`^\\[fork ${forkResult.message.details.name} done\\]`));
});
