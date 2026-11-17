import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { type Run } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";
import { digestLine, wakeReason } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/wake.ts";

const run = (patch: Partial<Run> = {}): Run => ({ id: "a", name: "scan", role: "reader", background: true, state: "done", task: "t", outcome: "done", ref: "rc-fork-scan", startedAt: 1, ...patch });

describe("wakeReason", () => {
	test("every finished run wakes main, while a live or cancelled run does not", () => {
		assert.equal(wakeReason(run()), "finished");
		assert.equal(wakeReason(run({ notify: true })), "notify");
		assert.equal(wakeReason(run({ state: "blocked", outcome: "blocked-on-user" })), "blocked-on-user");
		assert.equal(wakeReason(run({ state: "blocked", outcome: "done" })), "blocked-on-user");
		assert.equal(wakeReason(run({ state: "failed", outcome: "failed" })), "failed");
		assert.equal(wakeReason(run({ state: "failed", outcome: undefined })), "error");
		assert.equal(wakeReason(run({ state: "lost", outcome: undefined })), "lost");
		assert.equal(wakeReason(run({ outcome: "maybe" })), "invalid");
		assert.equal(wakeReason(run({ outcome: undefined })), "invalid");
		assert.equal(wakeReason(run({ state: "cancelled", outcome: undefined })), undefined);
		assert.equal(wakeReason(run({ state: "landing", outcome: undefined })), undefined);
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

	test("puts the note before the ref", () => {
		assert.equal(digestLine(run(), "OUTCOME done ref:rc-fork-scan", "[merge: landed abc]"), "[fork scan done] [merge: landed abc] ref rc-fork-scan");
	});

	test("never cuts an ASK or DENIED line and marks the cut of the rest with the ref", () => {
		const asks = `ASK: ${"q".repeat(600)}\nDENIED: "${"d".repeat(600)}"`;
		const line = digestLine(run({ outcome: "blocked-on-user" }), `${"y".repeat(900)}\n${asks}`);
		assert.ok(line.includes(`ASK: ${"q".repeat(600)}`));
		assert.ok(line.includes(`DENIED: "${"d".repeat(600)}"`));
		assert.ok(!line.includes("y".repeat(501)));
		assert.ok(line.includes("… (cut, result_fetch rc-fork-scan)"));
	});

	test("cuts a reply without a valid OUTCOME line", () => {
		const line = digestLine(run({ outcome: undefined, state: "failed" }), "y".repeat(2000));
		assert.ok(line.length < 700);
		assert.match(line, /^\[fork scan failed\] y+/);
	});
});
