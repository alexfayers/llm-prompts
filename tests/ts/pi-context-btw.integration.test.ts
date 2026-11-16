// Real-model check that //btw answers outside the main context. Runs only with PI_CONTEXT_INTEGRATION=1 and PI_CONTEXT_AGENT_DIR set to a scratch agent directory.
// Env: PI_CONTEXT_PI (the pi command, default pi), PI_CONTEXT_MODEL (required)
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { integrationModel } from "./helpers.ts";
import { RpcChild } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/runner.ts";

const WAIT_MS = 180_000;
const entriesOf = (dir: string) => fs.readdirSync(dir, { recursive: true, encoding: "utf8" }).filter((file) => file.endsWith(".jsonl")).flatMap((file) => fs.readFileSync(path.join(dir, file), "utf8").trim().split("\n").map((line) => JSON.parse(line)));
const messagesOf = (dir: string) => entriesOf(dir).filter((entry) => entry.type === "message");

test("//btw stores an answer that knows the session and adds no message to it", { skip: !process.env.PI_CONTEXT_INTEGRATION, timeout: WAIT_MS + 120_000 }, async () => {
	const agentDir = process.env.PI_CONTEXT_AGENT_DIR;
	assert.ok(agentDir && path.resolve(agentDir) !== path.join(os.homedir(), ".pi", "agent"), "PI_CONTEXT_AGENT_DIR must name a scratch agent directory");
	const work = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-btw-it-"));
	const sessions = path.join(work, "sessions");
	const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(PI|HERDR)_/.test(key)));
	const main = RpcChild.start({
		command: [process.env.PI_CONTEXT_PI ?? "pi"],
		args: ["--mode", "rpc", "--session-dir", sessions, "--model", integrationModel(), "--thinking", "off"],
		cwd: work,
		env: { ...env, PI_CODING_AGENT_DIR: agentDir, PI_CACHE_RETENTION: "long", PI_SKIP_VERSION_CHECK: "1" },
		onUi: () => undefined,
	});
	try {
		assert.equal((await main.prompt("Remember the code word PELICAN. Reply with the single word ready.")).error, undefined);
		const before = messagesOf(sessions).length;
		assert.equal((await main.prompt("//btw What was the code word? Answer with just the word.")).error, undefined);
		const deadline = Date.now() + WAIT_MS;
		while (!entriesOf(sessions).some((entry) => entry.customType === "pi-context-btw") && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 500));
		const stored = entriesOf(sessions).filter((entry) => entry.customType === "pi-context-btw");
		assert.equal(stored.length, 1, "one stored btw answer");
		assert.match(stored[0].data.a, /pelican/i);
		assert.equal(messagesOf(sessions).length, before, "no message added to the session");
	} finally {
		await main.close();
	}
});
