import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

const call = (id: string, command: string) => ({ role: "assistant", content: [{ type: "toolCall", id, name: "bash", arguments: { command } }] });
const result = (id: string, text: string, isError = false) => ({ role: "toolResult", toolCallId: id, toolName: "bash", content: [{ type: "text", text }], isError });
const FILLER = Array.from({ length: 60 }, (_, index) => `tests/test_${index}.py::test_ok PASSED`).join("\n");
const FAILING = `${FILLER}\nE   assert 1 == 2\nE   AssertionError: totals differ\nFAILED tests/test_a.py::test_total - assert 1 == 2\nFAILED tests/test_b.py::test_sum\n=== 2 failed, 60 passed in 1.20s ===\n\nCommand exited with code 1`;
const PASSING = `${FILLER}\n=== 60 passed in 1.20s ===`;

/** A session where `command` ran as call `c1`, then `acted` says whether a later tool call used its result. */
async function settle(command: string, output: string, { isError = false, acted = true, stored = [] as object[] } = {}) {
	const ext = await loadExtension("test-output-fold");
	const messages = [call("c1", command), result("c1", output, isError), ...(acted ? [call("c2", "git diff")] : [])];
	const entries = messages.map((message, index) => ({ sourceEntry: { id: `e${index}` }, messages: [message] }));
	const ctx = ext.makeCtx({ sessionManager: { getBranch: () => stored } as any });
	await ext.fire("tool_result", { toolCallId: "c1", toolName: "bash", input: { command }, content: [{ type: "text", text: output }], isError }, ctx);
	const out = await ext.fire("turn_end", { outcome: "completed", entries: [], context: { contextEntries: entries } }, ctx);
	return { added: (out?.entries ?? []) as any[] };
}

describe("turn_end", () => {
	test("a failing test run acted on by a later call becomes a summary of its failures, with its full text kept under a ref", async () => {
		const { added } = await settle("PYTEST_XDIST_AUTO_NUM_WORKERS=4 uv run pytest -q", FAILING, { isError: true });
		const edit = added.find((draft) => draft.type === "context_edit");
		assert.equal(edit.targetId, "e1");
		const summary = edit.replacement.content[0].text;
		assert.match(summary, /^\[test run: PYTEST_XDIST_AUTO_NUM_WORKERS=4 uv run pytest -q failed \(exit 1\)/);
		for (const line of ["FAILED tests/test_a.py::test_total - assert 1 == 2", "FAILED tests/test_b.py::test_sum", "E   AssertionError: totals differ", "=== 2 failed, 60 passed in 1.20s ==="]) assert.ok(summary.includes(line), line);
		assert.ok(summary.includes('result_fetch({ref:"rc-c1"})'));
		assert.ok(summary.length < FAILING.length / 3);
		assert.deepEqual(added.find((draft) => draft.customType === "result-cap").data, { ref: "rc-c1", text: FAILING });
	});

	test("a python -m pytest run is a test run", async () => {
		const { added } = await settle("cd app && python3 -m pytest -q", FAILING, { isError: true });
		assert.match(added.find((draft) => draft.type === "context_edit").replacement.content[0].text, /^\[test run: cd app && python3 -m pytest -q failed/);
	});

	test("a passing run keeps only its verdict and tally line", async () => {
		const { added } = await settle("just", PASSING);
		const summary = added.find((draft) => draft.type === "context_edit").replacement.content[0].text;
		assert.match(summary, /^\[test run: just passed\n=== 60 passed in 1.20s ===\n/);
	});

	test("a run whose full text the result cap already stored is summarized from that text", async () => {
		const capped = `${FAILING.slice(0, 100)}\n[capped: ${FAILING.length} chars, ref rc-c1; result_fetch({ref, offset?, limit?, pattern?})]\n${FAILING.slice(-100)}`;
		const { added } = await settle("just", capped, { isError: true, stored: [{ customType: "result-cap", data: { ref: "rc-c1", text: FAILING } }] });
		assert.equal(added.some((draft) => draft.customType === "result-cap"), false);
		assert.ok(added.find((draft) => draft.type === "context_edit").replacement.content[0].text.includes("FAILED tests/test_a.py::test_total"));
	});

	test("output no later call has used, a short run, a command that is not a runner and output with an ASK line stay as they are", async () => {
		assert.deepEqual((await settle("just", FAILING, { isError: true, acted: false })).added, []);
		assert.deepEqual((await settle("just", "ok", { acted: true })).added, []);
		assert.deepEqual((await settle("git log && echo just done", FAILING, { isError: true })).added, []);
		assert.deepEqual((await settle("just", `${FAILING}\nASK: which one?`, { isError: true })).added, []);
	});

	test("a run already summarized is not summarized again", async () => {
		const ext = await loadExtension("test-output-fold");
		const ctx = ext.makeCtx({ sessionManager: { getBranch: () => [] } as any });
		const entries = [call("c1", "just"), result("c1", FAILING, true), call("c2", "ls")].map((message, index) => ({ sourceEntry: { id: `e${index}` }, messages: [message] }));
		await ext.fire("tool_result", { toolCallId: "c1", toolName: "bash", input: { command: "just" }, content: [], isError: true }, ctx);
		const turnEnd = () => ext.fire("turn_end", { outcome: "completed", entries: [], context: { contextEntries: entries } }, ctx);
		assert.ok(await turnEnd());
		assert.equal(await turnEnd(), undefined);
	});
});
