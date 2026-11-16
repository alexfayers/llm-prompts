// Real-model check that a writer fork resolves a rebase conflict itself and lands. Runs only with PI_CONTEXT_INTEGRATION=1 and PI_CONTEXT_AGENT_DIR set to a scratch agent directory.
// Env: PI_CONTEXT_PI (the pi command, default pi), PI_CONTEXT_MODEL (required)
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { integrationModel } from "./helpers.ts";
import { RpcChild } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/runner.ts";

const git = (cwd: string, ...args: string[]) => execFileSync("git", args, { cwd, encoding: "utf8", stdio: "pipe" }).trim();
const entriesOf = (dir: string) => fs.readdirSync(dir, { recursive: true, encoding: "utf8" }).filter((file) => file.endsWith(".jsonl")).flatMap((file) => fs.readFileSync(path.join(dir, file), "utf8").trim().split("\n").map((line) => JSON.parse(line)));

test("a writer fork resolves a rebase conflict and its commits land on the main checkout", { skip: !process.env.PI_CONTEXT_INTEGRATION, timeout: 600_000 }, async (t) => {
	const agentDir = process.env.PI_CONTEXT_AGENT_DIR;
	assert.ok(agentDir && path.resolve(agentDir) !== path.join(os.homedir(), ".pi", "agent"), "PI_CONTEXT_AGENT_DIR must name a scratch agent directory");
	const work = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-writer-it-")));
	const repo = path.join(work, "repo");
	fs.mkdirSync(repo);
	git(repo, "init", "-b", "main");
	git(repo, "config", "user.email", "t@example.com");
	git(repo, "config", "user.name", "t");
	git(repo, "commit", "--allow-empty", "-m", "start");
	const flag = path.join(work, "ran");
	const tests = path.join(work, "tests.sh");
	fs.writeFileSync(tests, `[ -e ${flag} ] && exit 0\ntouch ${flag}\ncd ${repo} && echo "main side" > target.txt && git add target.txt && git commit -qm main-side\n`);
	const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(PI|HERDR)_/.test(key)));
	const main = RpcChild.start({
		command: [process.env.PI_CONTEXT_PI ?? "pi"],
		args: ["--mode", "rpc", "--session-dir", path.join(work, "sessions"), "--model", integrationModel(), "--thinking", "off"],
		cwd: repo,
		env: { ...env, PI_CODING_AGENT_DIR: agentDir, PI_CONTEXT_TEST_CMD: `sh ${tests}`, PI_SKIP_VERSION_CHECK: "1" },
		onUi: (request) => (request.method === "confirm" ? { confirmed: true } : request.method === "select" ? { value: (request.options as string[])[0] } : undefined),
	});
	try {
		const task = "Create target.txt with the single line `fork side` and commit it. If you are told about a rebase conflict, keep both lines in target.txt, finish the rebase and reply again.";
		const turn = await main.prompt(`Call the fork tool once with role writer, name conflict and this task: ${task} Then reply with the word finished.`);
		assert.equal(turn.error, undefined);
	} finally {
		await main.close();
	}
	const entries = entriesOf(path.join(work, "sessions"));
	const forkResult = entries.find((entry) => entry.message?.toolName === "fork");
	assert.ok(forkResult, "main called the fork tool");
	t.diagnostic(`fork result: ${JSON.stringify(forkResult.message.content)} merge: ${JSON.stringify(forkResult.message.details?.merge)}`);
	t.diagnostic(`main assistant turns: ${entries.filter((entry) => entry.message?.role === "assistant").length}`);
	t.diagnostic(`history: ${git(repo, "log", "--oneline", "main")}`);
	assert.equal(forkResult.message.details.merge.state, "landed");
	assert.equal(git(repo, "rev-list", "--count", "main"), "3");
	assert.equal(git(repo, "rev-list", "--merges", "--count", "main"), "0");
	const target = fs.readFileSync(path.join(repo, "target.txt"), "utf8");
	assert.match(target, /main side/);
	assert.match(target, /fork side/);
	assert.equal(git(repo, "worktree", "list").split("\n").length, 1);
});
