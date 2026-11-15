import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { type Run } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";
import { Coalescer, digestLine, wakeReason } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/wake.ts";

const run = (patch: Partial<Run> = {}): Run => ({ id: "a", name: "scan", role: "reader", background: true, state: "done", task: "t", outcome: "done", ref: "rc-fork-scan", startedAt: 1, ...patch });

describe("wakeReason", () => {
	test("a finished run wakes main only when it was the last live run, and a notify flag wakes it at once", () => {
		assert.equal(wakeReason(run(), 1), undefined);
		assert.equal(wakeReason(run({ state: "found-it", outcome: "found-it" }), 1), undefined);
		assert.equal(wakeReason(run(), 0), "all-done");
		assert.equal(wakeReason(run({ notify: true }), 1), "notify");
	});

	test("a run that needs main wakes it whatever else is live", () => {
		assert.equal(wakeReason(run({ state: "blocked", outcome: "blocked-on-user" }), 2), "blocked-on-user");
		assert.equal(wakeReason(run({ state: "blocked", outcome: "done" }), 2), "blocked-on-user");
		assert.equal(wakeReason(run({ state: "failed", outcome: "failed" }), 2), "failed");
		assert.equal(wakeReason(run({ state: "failed", outcome: undefined }), 2), "error");
		assert.equal(wakeReason(run({ state: "lost", outcome: undefined }), 2), "lost");
		assert.equal(wakeReason(run({ outcome: "maybe" }), 2), "invalid");
		assert.equal(wakeReason(run({ outcome: undefined }), 2), "invalid");
	});

	test("a cancelled run does not wake main", () => {
		assert.equal(wakeReason(run({ state: "cancelled", outcome: undefined }), 0), undefined);
	});
});

describe("digestLine", () => {
	const header = "OUTCOME blocked-on-user ref:rc-fork-scan";

	test("heads the line with the run and its code, keeps ASK and DENIED lines and ends with the ref", () => {
		const text = `${header}\nlong report\nASK: use A or B?\nmore\nDENIED: "no"`;
		assert.equal(digestLine(run({ outcome: "blocked-on-user" }), text), `[fork scan blocked-on-user] ASK: use A or B?\nDENIED: "no" ref rc-fork-scan`);
	});

	test("keeps a short found-it line and drops a long one", () => {
		const head = "OUTCOME found-it ref:rc-fork-scan";
		assert.equal(digestLine(run({ outcome: "found-it" }), `${head}\nsrc/a.ts:12\nmore`), "[fork scan found-it] src/a.ts:12 ref rc-fork-scan");
		assert.equal(digestLine(run({ outcome: "found-it" }), `${head}\n${"x".repeat(201)}`), "[fork scan found-it] ref rc-fork-scan");
	});

	test("cuts a reply without a valid OUTCOME line", () => {
		const line = digestLine(run({ outcome: undefined, state: "failed" }), "y".repeat(2000));
		assert.ok(line.length < 700);
		assert.match(line, /^\[fork scan failed\] y+/);
	});
});

describe("Coalescer", () => {
	test("hands over the lines of the finished runs once", () => {
		const coalescer = new Coalescer();
		coalescer.add(run({ name: "a" }), "OUTCOME done ref:rc-fork-a");
		coalescer.add(run({ name: "b" }), "OUTCOME done ref:rc-fork-b");
		assert.deepEqual(coalescer.take(), ["[fork a done] ref rc-fork-scan", "[fork b done] ref rc-fork-scan"]);
		assert.deepEqual(coalescer.take(), []);
	});
});
