import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { MAX_STEPS, Recorder } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/ghost/recorder.ts";

const call = (id: string, toolName: string, input: Record<string, unknown> = {}) => ({ type: "tool_call", toolCallId: id, toolName, input }) as any;
const result = (id: string, toolName: string, text = "", isError = false, input: Record<string, unknown> = {}) => ({ type: "tool_result", toolCallId: id, toolName, input, content: [{ type: "text", text }], isError }) as any;

/** Records the calls as one run that settles. */
function record(steps: [string, string, string?, boolean?][], aborted = false) {
	const recorder = new Recorder();
	recorder.onInput();
	for (const [id, tool, text, isError] of steps) {
		recorder.onCall(call(id, tool, { id }));
		recorder.onResult(result(id, tool, text, isError, { id }));
	}
	recorder.onSettled({ aborted });
	return recorder;
}

describe("Recorder", () => {
	test("records the steps of a settled run in order with their arguments and output, and calls it clean", () => {
		const last = record([["a", "read", "one"], ["b", "bash", "two"]]).last()!;
		assert.deepEqual(last.steps.map((step) => [step.tool, step.args, step.isError, step.check]), [["read", { id: "a" }, false, null], ["bash", { id: "b" }, false, null]]);
		assert.deepEqual(last.outputs, ["one", "two"]);
		assert.equal(last.clean, true);
	});

	test("attaches calls a tool made to its step, and keeps only the first 4 KB of output", () => {
		const recorder = new Recorder();
		recorder.onInput();
		recorder.onCall(call("c1", "codemode"));
		recorder.onCall({ ...call("c1/1", "read"), parentToolCallId: "c1" });
		recorder.onResult({ ...result("c1/1", "read", "x", true), parentToolCallId: "c1" });
		recorder.onCall({ ...call("c1/2", "grep"), parentToolCallId: "c1" });
		recorder.onResult({ ...result("c1/2", "grep", "y"), parentToolCallId: "c1" });
		recorder.onResult(result("c1", "codemode", "z".repeat(5000)));
		recorder.onSettled({ aborted: false });
		const last = recorder.last()!;
		assert.equal(last.steps.length, 1);
		assert.deepEqual(last.steps[0].nested, [{ tool: "read", isError: true }, { tool: "grep", isError: false }]);
		assert.equal(last.outputs[0].length, 4096);
		assert.equal(last.clean, false);
	});

	test("is not clean when aborted, when a step failed, when it holds a tool that cannot be replayed, or when it has too many steps", () => {
		assert.equal(record([["a", "read"]], true).last()!.clean, false);
		assert.equal(record([["a", "read", "boom", true]]).last()!.clean, false);
		assert.equal(record([["a", "read"], ["b", "fork"]]).last()!.clean, false);
		assert.equal(record(Array.from({ length: MAX_STEPS + 1 }, (_, i) => [`s${i}`, "read"] as [string, string])).last()!.clean, false);
		assert.equal(record(Array.from({ length: MAX_STEPS }, (_, i) => [`s${i}`, "read"] as [string, string])).last()!.clean, true);
		const unanswered = new Recorder();
		unanswered.onCall(call("a", "read"));
		unanswered.onSettled({ aborted: false });
		assert.equal(unanswered.last()!.clean, false);
	});

	test("is not clean when a nested call used a tool that cannot be replayed", () => {
		const recorder = new Recorder();
		recorder.onCall(call("c1", "codemode"));
		recorder.onCall({ ...call("c1/1", "delegate_agent"), parentToolCallId: "c1" });
		recorder.onResult({ ...result("c1/1", "delegate_agent"), parentToolCallId: "c1" });
		recorder.onResult(result("c1", "codemode"));
		recorder.onSettled({ aborted: false });
		assert.equal(recorder.last()!.clean, false);
	});

	test("ignores the calls a ghost_run made, so only the ghost_run step is recorded", () => {
		const recorder = new Recorder();
		recorder.onCall(call("g1", "ghost_run"));
		recorder.onCall({ ...call("g1/1", "bash"), parentToolCallId: "g1" });
		recorder.onResult({ ...result("g1/1", "bash", "inner"), parentToolCallId: "g1" });
		recorder.onResult(result("g1", "ghost_run", "ghost ok"));
		recorder.onSettled({ aborted: false });
		const last = recorder.last()!;
		assert.deepEqual(last.steps.map((step) => [step.tool, step.nested]), [["ghost_run", undefined]]);
		assert.equal(last.clean, false);
	});

	test("a new input starts a new run, and a settled run with no steps keeps the previous one", () => {
		const recorder = record([["a", "read"]]);
		recorder.onInput();
		recorder.onSettled({ aborted: false });
		assert.equal(recorder.last()!.steps[0].tool, "read");
		recorder.onCall(call("b", "bash"));
		recorder.onInput();
		recorder.onCall(call("c", "grep"));
		recorder.onResult(result("c", "grep"));
		recorder.onSettled({ aborted: false });
		assert.deepEqual(recorder.last()!.steps.map((step) => step.tool), ["grep"]);
		assert.equal(new Recorder().last(), undefined);
	});
});

describe("the pi-context extension", () => {
	const dir = mkdtempSync(join(tmpdir(), "ghost-recorder-"));
	after(() => rmSync(dir, { recursive: true }));
	const handshake = join(dir, "handshake.json");
	writeFileSync(handshake, JSON.stringify({ role: "reader" }));
	useEnv({ PI_CONTEXT_CHILD: undefined });

	test("records the run in the main session and not in a delegate", async () => {
		assert.ok((await loadExtension("pi-context/index")).handlers.agent_settled);
		process.env.PI_CONTEXT_CHILD = handshake;
		assert.equal((await loadExtension("pi-context/index")).handlers.agent_settled, undefined);
	});
});
