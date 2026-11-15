import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, beforeEach, describe, test } from "node:test";
import { repoKey, stepsHash } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/ghost/model.ts";
import { loadExtension, type LoadedExtension, useEnv } from "./helpers.ts";

const git = (cwd: string, ...args: string[]) => execFileSync("git", ["-c", "user.name=t", "-c", "user.email=t@example.com", ...args], { cwd, stdio: "pipe" });
const dirs: string[] = [];
const tmp = () => (dirs.push(mkdtempSync(join(tmpdir(), "ghost-command-"))), realpathSync(dirs.at(-1)!));
after(() => dirs.forEach((dir) => rmSync(dir, { recursive: true })));

type Call = [tool: string, input: Record<string, unknown>, output: string];
const mode = (path: string) => statSync(path).mode & 0o777;

describe("/ghost", () => {
	useEnv({ PI_CONTEXT_CHILD: undefined });
	let repo: string;
	let agentDir: string;
	let ext: LoadedExtension;
	const ghostsDir = () => join(agentDir, "ghosts", repoKey(repo));
	const ghostFiles = () => (existsSync(ghostsDir()) ? readdirSync(ghostsDir()) : []);

	beforeEach(async () => {
		repo = tmp();
		agentDir = tmp();
		git(repo, "init", "-b", "main");
		git(repo, "commit", "--allow-empty", "-m", "init");
		ext = await loadExtension("pi-context/index", { agentDir, ctx: { cwd: repo } });
	});

	const ran = async (calls: Call[], aborted = false) => {
		for (const [index, [toolName, input, text]] of calls.entries()) {
			await ext.fire("tool_call", { toolCallId: `c${index}`, toolName, input });
			await ext.fire("tool_result", { toolCallId: `c${index}`, toolName, input, content: [{ type: "text", text }], isError: false });
		}
		await ext.fire("agent_settled", { aborted });
	};
	const command = async (args: string) => {
		const before = ext.ctx.notices.length;
		await ext.runCommand("ghost", args);
		return ext.ctx.notices.slice(before).map(([text]) => text).join("\n");
	};

	test("saves a read-only run as a private file under the agent directory with checks and parameters, and lists it", async () => {
		await ran([["read", { path: "src/a.ts" }, "ok"], ["grep", { pattern: "foo", path: "src" }, "src/a.ts:1:foo"]]);
		await command("save peek path=src/a.ts");
		const file = join(ghostsDir(), "peek.json");
		const ghost = JSON.parse(readFileSync(file, "utf8"));
		assert.deepEqual(ghost.steps.map((step: any) => [step.tool, step.args, step.check]), [
			["read", { path: "{{path}}" }, { isError: false, output: { exact: "ok" } }],
			["grep", { pattern: "foo", path: "src" }, { isError: false, output: { exact: "{{path}}:1:foo" } }],
		]);
		assert.equal(ghost.params.path.default, "src/a.ts");
		assert.deepEqual([ghost.repoKey, ghost.branch, ghost.approvedHash], [repoKey(repo), "main", undefined]);
		assert.deepEqual([mode(file), mode(ghostsDir()), mode(join(agentDir, "ghosts"))], [0o600, 0o700, 0o700]);
		assert.match(await command("list"), /peek.*2 steps/);
		assert.deepEqual(readdirSync(repo).filter((name) => name !== ".git"), []);
	});

	test("refuses when there is no run to save, the run cannot be replayed, the name or a parameter is invalid, or a step holds a secret, and writes nothing", async () => {
		assert.match(await command("save x"), /no run/i);
		await ran([["read", {}, "ok"]], true);
		assert.match(await command("save x"), /cannot be saved/);
		await ran([["read", {}, "ok"]]);
		assert.match(await command("save Bad_Name"), /lowercase letters/);
		assert.match(await command("save x path=a;b"), /parameter path/);
		await ran([["bash", { command: "export K=AKIAABCDEFGHIJKLMNOP" }, ""]]);
		const refusal = await command("save x");
		assert.match(refusal, /Step 1 \(bash\).*aws-access-key/);
		assert.ok(!refusal.includes("AKIAABCDEFGHIJKLMNOP"));
		assert.deepEqual(ghostFiles(), []);
	});

	test("a step that can change things needs one approval at save, which records what was approved, and none without a prompt", async () => {
		const asked: string[][] = [];
		let answer = false;
		(ext.ctx.ui as any).confirm = async (title: string, message: string) => (asked.push([title, message]), answer);
		await ran([["bash", { command: "git status --short" }, ""]]);
		assert.match(await command("save status"), /Not saved/);
		assert.deepEqual(ghostFiles(), []);
		assert.match(asked[0].join("\n"), /status.*1\. bash.*git status --short/s);
		answer = true;
		await command("save status");
		const ghost = JSON.parse(readFileSync(join(ghostsDir(), "status.json"), "utf8"));
		assert.equal(ghost.approvedHash, stepsHash(ghost.steps));
		assert.equal(asked.length, 2);
		const headless = ext.makeCtx({ cwd: repo, hasUI: false });
		await ext.runCommand("ghost", "save other", headless);
		assert.match(headless.notices[0][0], /interactive/);
		assert.deepEqual(ghostFiles(), ["status.json"]);
	});

	test("a step without an automatic check is written to a draft that save validates once the check is added", async () => {
		await ran([["read", { path: "a" }, "ok"], ["read", { path: "b" }, "commit 0a1b2c3d4e5f"]]);
		assert.match(await command("save d"), /Step 2 has no check.*d\.draft\.json/s);
		const draft = join(ghostsDir(), "d.draft.json");
		assert.deepEqual([ghostFiles(), mode(draft)], [["d.draft.json"], 0o600]);
		assert.equal(await command("list"), "No ghosts for this repository.");
		assert.match(await command("save d"), /Step 2 has no check/);
		assert.match(await command("save d x=y"), /already in the draft/);
		const edited = JSON.parse(readFileSync(draft, "utf8"));
		edited.steps[1].check = { isError: false, output: { regex: "^commit [0-9a-f]+$" } };
		writeFileSync(draft, JSON.stringify(edited));
		assert.match(await command("save d"), /Saved ghost d \(2 steps\)/);
		assert.deepEqual(ghostFiles(), ["d.json"]);
		edited.steps[1].args = { path: "AKIAABCDEFGHIJKLMNOP" };
		writeFileSync(draft, JSON.stringify(edited));
		assert.match(await command("save d"), /Step 2.*aws-access-key/);
	});

	test("a file that is not a ghost is reported by name", async () => {
		await ran([["read", {}, "ok"]]);
		await command("save good");
		writeFileSync(join(ghostsDir(), "bad.json"), '{"version":2}');
		assert.match(await command("list"), /bad\.json: it is not a ghost file/);
	});
});
