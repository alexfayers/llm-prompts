import assert from "node:assert/strict";
import { test } from "node:test";
import { parseOutcome, projectResult } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/outcome.ts";

test("a coded reply is reduced to its OUTCOME line and the start of its body", () => {
	assert.equal(projectResult("preamble\nOUTCOME done ref:r1\nReport line one.\n\nReport line two."), "OUTCOME done ref:r1\nReport line one.\nReport line two.");
	assert.equal(projectResult("prose\nOUTCOME done ref:r1 1a2b3c4\nreport"), "OUTCOME done ref:r1 1a2b3c4\nreport");
	assert.equal(projectResult("OUTCOME done ref:r1\t1a2b3c4\nreport"), "OUTCOME done ref:r1\t1a2b3c4\nreport");
	assert.equal(projectResult("OUTCOME done ref:\nreport"), "OUTCOME done ref:\nreport");
	assert.equal(projectResult("OUTCOME done ref: 1a2b3c4\nreport"), "OUTCOME done ref: 1a2b3c4\nreport");
	assert.equal(projectResult("no code\nhere"), "no code\nhere");
});

test("the body after the OUTCOME line is cut at 600 characters", () => {
	const code = "OUTCOME done ref:r1";
	assert.equal(projectResult(`${code}\n${"x".repeat(700)}`), `${code}\n${"x".repeat(600)}`);
	assert.equal(projectResult(`${code}\n${"a".repeat(500)}\n${"b".repeat(500)}`), `${code}\n${"a".repeat(500)}\n${"b".repeat(99)}`);
});

test("ASK and DENIED lines are kept in full wherever they are", () => {
	const ask = `ASK: ${"q".repeat(700)}`;
	assert.equal(projectResult(`${ask}\nOUTCOME blocked-on-user ref:r1\n${"x".repeat(700)}\nDENIED: "no"`), `${ask}\nOUTCOME blocked-on-user ref:r1\n${"x".repeat(600)}\nDENIED: "no"`);
});

test("parseOutcome reads the code, the notify flag and the ref from the OUTCOME line anywhere in the text", () => {
	assert.deepEqual(parseOutcome("body\nOUTCOME blocked-on-user notify ref:rc-fork-x\nASK: q?"), { code: "blocked-on-user", notify: true, ref: "rc-fork-x" });
	assert.deepEqual(parseOutcome("OUTCOME maybe ref:rc-y"), { code: "maybe", notify: false, ref: "rc-y" });
	assert.equal(parseOutcome("OUTCOME done"), undefined);
	assert.deepEqual(parseOutcome("OUTCOME done ref:"), { code: "done", notify: false, ref: "" });
	assert.equal(parseOutcome("OUTCOME done ref: 1a2b3c4"), undefined);
	assert.equal(parseOutcome("no code here"), undefined);
	assert.deepEqual(parseOutcome("prose first\nOUTCOME done ref:rc-x 1a2b3c4\nmore"), { code: "done", notify: false, ref: "rc-x" });
	assert.deepEqual(parseOutcome("OUTCOME found-it ref:rc-x \nthe answer"), { code: "found-it", notify: false, ref: "rc-x" });
});

test("a long run of emoji with no OUTCOME line matches nothing", { timeout: 5000 }, () => {
	assert.equal(parseOutcome("✅".repeat(50)), undefined);
	assert.equal(projectResult("✅".repeat(50)), "✅".repeat(50));
});

test("an OUTCOME line may open with an emoji", () => {
	assert.deepEqual(parseOutcome("🦩 OUTCOME done ref:"), { code: "done", notify: false, ref: "" });
	assert.equal(projectResult("🦩 OUTCOME done ref:r1\nbody"), "🦩 OUTCOME done ref:r1\nbody");
	assert.equal(parseOutcome("see OUTCOME done ref:r1"), undefined);
	for (const emoji of ["ℹ️", "1️⃣"]) {
		assert.deepEqual(parseOutcome(`${emoji} OUTCOME done ref:r1`), { code: "done", notify: false, ref: "r1" });
		assert.equal(projectResult(`${emoji} OUTCOME done ref:r1\nbody`), `${emoji} OUTCOME done ref:r1\nbody`);
	}
});
