import assert from "node:assert/strict";
import { test } from "node:test";
import { parseOutcome, projectResult } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/outcome.ts";

test("a coded reply is reduced to its OUTCOME line", () => {
	assert.equal(projectResult("preamble\nOUTCOME done ref:r1\nLong report line one.\nLong report line two."), "OUTCOME done ref:r1");
	assert.equal(projectResult("no code\nhere"), "no code\nhere");
});

test("found-it keeps a short next line and drops a long one", () => {
	const code = "OUTCOME found-it ref:r1";
	assert.equal(projectResult(`${code}\n\nsrc/a.ts:12\nmore`), `${code}\nsrc/a.ts:12`);
	assert.equal(projectResult(`${code}\n${"x".repeat(201)}`), code);
});

test("ASK and DENIED lines are kept wherever they are", () => {
	assert.equal(projectResult('OUTCOME blocked-on-user ref:r1\ndetails\nASK: use A or B?\nmore\nDENIED: "no"'), 'OUTCOME blocked-on-user ref:r1\nASK: use A or B?\nDENIED: "no"');
});

test("parseOutcome reads the code, the notify flag and the ref from the OUTCOME line anywhere in the text", () => {
	assert.deepEqual(parseOutcome("body\nOUTCOME blocked-on-user notify ref:rc-fork-x\nASK: q?"), { code: "blocked-on-user", notify: true, ref: "rc-fork-x" });
	assert.deepEqual(parseOutcome("OUTCOME maybe ref:rc-y"), { code: "maybe", notify: false, ref: "rc-y" });
	assert.equal(parseOutcome("OUTCOME done"), undefined);
	assert.equal(parseOutcome("OUTCOME done ref:"), undefined);
	assert.equal(parseOutcome("no code here"), undefined);
	assert.equal(parseOutcome("OUTCOME done ref:rc-x trailing words"), undefined);
	assert.deepEqual(parseOutcome("OUTCOME found-it ref:rc-x \nthe answer"), { code: "found-it", notify: false, ref: "rc-x" });
});
