import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { checkResult, deriveCheck, findSecret, parameterize, render, type Step, stepsHash } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/ghost/model.ts";

const step = (tool: string, args: Record<string, unknown>): Step => ({ tool, args, check: null, isError: false });

describe("parameterize and render", () => {
	test("a parameter value and an earlier step's output become placeholders that render back to the originals", () => {
		const steps = [step("bash", { command: "git rev-parse feat/x" }), step("bash", { command: "git checkout feat/x && git merge abcdef12", nested: ["abcdef12"] })];
		const made = parameterize(steps, { branch: "feat/x" }, ["abcdef12\n", ""]);
		assert.deepEqual(made[0].args, { command: "git rev-parse {{branch}}" });
		assert.deepEqual(made[1].args, { command: "git checkout {{branch}} && git merge {{step1}}", nested: ["{{step1}}"] });
		assert.deepEqual(render(made[1].args, { branch: "feat/x", step1: "abcdef12" }), { value: steps[1].args });
		assert.deepEqual(parameterize([step("bash", { command: "cat a.txt" })], { n: "a" })[0].args, { command: "cat {{n}}.txt" });
	});

	test("a short or multi-line output is left alone, and a step's own output is not referenced by itself", () => {
		const made = parameterize([step("bash", { command: "echo main" }), step("bash", { command: "echo main line" })], {}, ["main", "main\nline"]);
		assert.deepEqual(made.map((s) => s.args), [{ command: "echo main" }, { command: "echo main line" }]);
		assert.deepEqual(parameterize([step("bash", { command: "echo longvalue" })], {}, ["longvalue"])[0].args, { command: "echo longvalue" });
	});

	test("render names the first variable that is missing", () => {
		assert.deepEqual(render({ a: ["x {{one}} {{two}}"] }, { one: "1" }), { missing: "two" });
	});
});

describe("checks", () => {
	test("empty output derives an empty check and short stable output an exact one", () => {
		assert.deepEqual(deriveCheck(" \n", false), { isError: false, output: { empty: true } });
		assert.deepEqual(deriveCheck("On branch main\nnothing to commit\n", false), { isError: false, output: { exact: "On branch main\nnothing to commit" } });
	});

	test("long output and output with a sha, a timestamp or a temp path derive no check", () => {
		assert.equal(deriveCheck("a\nb\nc\nd\ne\nf", false), null);
		assert.equal(deriveCheck("HEAD is 0a1b2c3d4e5f", false), null);
		assert.equal(deriveCheck("built at 2026-11-15T05:55:46Z", false), null);
		assert.equal(deriveCheck("wrote /tmp/x/out.json", false), null);
	});

	test("a result passes only when its error flag and its output match the check", () => {
		const exact = { isError: false, output: { exact: "ok" } };
		assert.equal(checkResult(exact, "\nok \n", false), true);
		assert.equal(checkResult(exact, "nope", false), false);
		assert.equal(checkResult(exact, "ok", true), false);
		assert.equal(checkResult({ isError: false, output: { empty: true } }, "x", false), false);
		assert.equal(checkResult({ isError: false, output: { regex: "^v\\d+$" } }, "v12", false), true);
		assert.equal(checkResult({ isError: false, output: { regex: "(" } }, "v12", false), false);
		assert.equal(checkResult({ isError: false }, "anything", false), true);
	});
});

describe("stepsHash", () => {
	test("is the same for the same steps whatever the key order, and differs when a step changes", () => {
		const a = step("bash", { command: "ls", cwd: "." });
		assert.equal(stepsHash([a]), stepsHash([step("bash", { cwd: ".", command: "ls" })]));
		assert.notEqual(stepsHash([a]), stepsHash([step("bash", { command: "rm", cwd: "." })]));
	});
});

describe("findSecret", () => {
	const cases: [string, string][] = [
		["aws-access-key", "export K=AKIAABCDEFGHIJKLMNOP"],
		["private-key", "-----BEGIN RSA PRIVATE KEY-----"],
		["github-token", "curl -H ghp_abcdefghijklmnopqrstuvwx"],
		["slack-token", "xoxb-12345-abcde"],
		["bearer-token", "Authorization: Bearer abcdefghijklmnopqrst"],
		["assigned-secret", "PASSWORD=hunter2"],
		["credential-path", "cat ~/.aws/credentials"],
	];
	for (const [pattern, command] of cases) {
		test(`names the step and the ${pattern} pattern without echoing the value`, () => {
			const found = findSecret([step("read", { path: "a" }), step("bash", { command })], {});
			assert.deepEqual(found, { step: 2, pattern });
			assert.ok(!JSON.stringify(found).includes(command));
		});
	}

	test("finds an environment value in the arguments or the expected output, and ignores short values and clean steps", () => {
		const env = { MY_API_TOKEN: "s3cr3t-value", SHORT_KEY: "abc", HOME: "/home/someone" };
		assert.deepEqual(findSecret([step("bash", { command: "echo s3cr3t-value" })], env), { step: 1, pattern: "env:MY_API_TOKEN" });
		const checked: Step = { ...step("bash", { command: "env" }), check: { isError: false, output: { exact: "s3cr3t-value" } } };
		assert.deepEqual(findSecret([checked], env), { step: 1, pattern: "env:MY_API_TOKEN" });
		assert.equal(findSecret([step("bash", { command: "echo abc /home/someone" })], env), undefined);
	});
});
