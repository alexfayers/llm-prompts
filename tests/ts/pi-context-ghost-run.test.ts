import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, beforeEach, describe, test } from "node:test";
import { VERSION } from "@earendil-works/pi-coding-agent";
import { type Check, type Ghost, repoKey, type Step, stepsHash } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/ghost/model.ts";
import { ghostPath, writeGhost } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/ghost/store.ts";
import { loadExtension, type LoadedExtension, useEnv } from "./helpers.ts";

const dirs: string[] = [];
const tmp = () => (dirs.push(mkdtempSync(join(tmpdir(), "ghost-run-"))), realpathSync(dirs.at(-1)!));
after(() => dirs.forEach((dir) => rmSync(dir, { recursive: true })));

const exact = (output: string): Check => ({ isError: false, output: { exact: output } });
const step = (tool: string, args: Record<string, unknown>, check: Check | null = exact("ok")): Step => ({ tool, args, check, isError: false });
const outcome = (text: string, isError = false) => ({ isError, result: { content: [{ type: "text", text }], details: {} } });

describe("ghost_run", () => {
	useEnv({ PI_CONTEXT_CHILD: undefined });
	let repo: string;
	let ext: LoadedExtension;
	let calls: [string, any][];
	let replies: Record<string, string>;

	beforeEach(async () => {
		repo = tmp();
		execFileSync("git", ["init", "-b", "main"], { cwd: repo, stdio: "pipe" });
		ext = await loadExtension("pi-context/index", { agentDir: tmp(), ctx: { cwd: repo } });
		calls = [];
		replies = {};
	});

	const keep = (name: string, steps: Step[], extra: Partial<Ghost> = {}) => {
		const ghost: Ghost = { version: 1, name, repoKey: repoKey(repo), branch: "main", piVersion: VERSION, params: {}, steps, ...(steps.some((s) => s.tool !== "read") ? { approvedHash: stepsHash(steps) } : {}), ...extra };
		return writeGhost(ghostPath(repoKey(repo), name), ghost);
	};
	const ctxWith = (tools = ["read", "bash"]) =>
		ext.makeCtx({ cwd: repo, tools: tools.map((name) => ({ name })), executeTool: async (tool: string, args: unknown) => (calls.push([tool, args]), outcome(replies[`${tool}:${calls.length}`] ?? "ok")) } as any);
	const run = (params: Record<string, unknown>, ctx = ctxWith(), signal?: AbortSignal) => ext.tools.ghost_run.execute("id", params, signal, undefined, ctx);

	test("replays every step in order with the parameters and earlier outputs filled in, and reports success", async () => {
		await keep("go", [step("read", { path: "{{path}}" }, exact("0123456789")), step("bash", { command: "cat {{step1}} {{path}}" })], { params: { path: { default: "a.txt", pattern: "^[a-z.]+$" } } });
		replies["read:1"] = "0123456789";
		const result = await run({ name: "go", params: { path: "b.txt" } });
		assert.deepEqual(calls, [["read", { path: "b.txt" }], ["bash", { command: "cat 0123456789 b.txt" }]]);
		assert.match(result.content[0].text, /^ghost go ok \(2 steps\)/);
		assert.deepEqual(result.details.steps.map((s: any) => s.tool), ["read", "bash"]);
	});

	test("stops at the first step whose result fails its check, never retries, and reports the step, its check, the output and the steps done", async () => {
		await keep("stop", [step("read", { path: "a" }), step("bash", { command: "git status --porcelain" }, { isError: false, output: { empty: true } }), step("bash", { command: "git merge" })]);
		replies["read:1"] = "ok";
		replies["bash:2"] = " M file.txt";
		const error = await run({ name: "stop" }).catch((caught: Error) => caught);
		assert.match(error.message, /diverged at step 2 of 3 \(bash\)/);
		assert.match(error.message, /git status --porcelain/);
		assert.match(error.message, /empty/);
		assert.match(error.message, / M file\.txt/);
		assert.match(error.message, /Done: 1\. read/);
		assert.equal(calls.length, 2);
	});

	test("stops before a step that uses an earlier output holding characters a parameter may not have", async () => {
		await keep("inject", [step("read", { path: "a" }, { isError: false, output: { regex: "." } }), step("bash", { command: "echo {{step1}}" })]);
		replies["read:1"] = "x; rm -r ~";
		const error = await run({ name: "inject" }).catch((caught: Error) => caught);
		assert.match(error.message, /diverged at step 2 of 2 \(bash\): the value of \{\{step1\}\} is not allowed/);
		assert.equal(calls.length, 1);
	});

	test("refuses a ghost whose changing steps were edited after approval, and runs no step", async () => {
		const approved = [step("bash", { command: "git status" })];
		await keep("edited", [step("bash", { command: "git push" })], { approvedHash: stepsHash(approved) });
		const error = await run({ name: "edited" }).catch((caught: Error) => caught);
		assert.match(error.message, /diverged at step 0 \(preflight\): its steps were not approved/);
		assert.equal(calls.length, 0);
	});
});
