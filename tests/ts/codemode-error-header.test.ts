import assert from "node:assert/strict";
import { test } from "node:test";
import { loadExtension } from "./helpers.ts";

const text = (value: string) => ({ type: "text", text: value });
const failed = (output: string, toolName = "codemode") => ({
	toolName,
	isError: true,
	content: [text("Script failed\nWall time 0.1 seconds\nOutput:\n"), text(output)],
});
const ext = await loadExtension("codemode-error-header");

test("failed header carries the first error line", async () => {
	const error = `Error: ${"x".repeat(500)}`;
	const output = `partial output\n\nScript error:\n${error}\n    at <anonymous> (codemode.js:1:39)`;
	const result = await ext.fire("tool_result", failed(output));
	assert.equal(result.content[0].text, `Script failed: ${error}\nWall time 0.1 seconds\nOutput:\n`);
	assert.deepEqual(result.content.slice(1), failed(output).content.slice(1));
});

test("everything else is left alone", async () => {
	const events = [
		{ toolName: "codemode", isError: false, content: [text("Script completed\nOutput:\n"), text("2")] },
		{ toolName: "codemode", isError: true, content: [text("Script failed\nOutput:\n")] },
		{ toolName: "codemode", isError: true, content: [text("Invalid options")] },
		failed("Script error:\nError: nope", "bash"),
	];
	for (const event of events) assert.equal(await ext.fire("tool_result", event), undefined);
});

const tools = new Proxy({ real: async (x: number) => x }, { get: (t, p) => (p in t ? t[p as keyof typeof t] : assert.fail(String(p))) });
const AsyncFunction = (async () => {}).constructor as new (...args: string[]) => (tools: unknown) => Promise<unknown>;
const ret = "return [typeof tools.nope, await tools.real(1)]";
for (const [label, code] of [
	["after options and directive prologue", `// @options: {"timeout_ms": 1}\n// note\n"use strict";\nif (this) throw Error("sloppy")\n${ret}`],
	["after a string statement continued onto the next line", `"ab"\n[0].toUpperCase()\n${ret}`],
]) {
	test(`missing tool read gives undefined: ${label}`, async () => {
		const input = { code };
		await ext.fire("tool_call", { toolName: "codemode", input });
		assert.deepEqual(await new AsyncFunction("tools", input.code)(tools), ["undefined", 1]);
		assert.equal(input.code.startsWith("// @options"), code.includes("@options"));
	});
}
