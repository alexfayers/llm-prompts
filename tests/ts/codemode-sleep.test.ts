import assert from "node:assert/strict";
import { mock, test } from "node:test";

mock.timers.enable({ apis: ["setTimeout"] });
mock.module("typebox", { namedExports: { Type: new Proxy({}, { get: () => () => ({}) }) } });
const { default: register } = await import("../../src/llm_prompts/prompts/pi/extensions/codemode-sleep.ts");

let tool: any;
register({ registerTool: (t: unknown) => (tool = t) } as any);
const sleep = (signal?: AbortSignal) =>
	tool.execute("id", { ms: 500 }, signal).then((r: any) => r.content[0].text, (e: Error) => e.name);

test("sleeps for the given time", async () => {
	let result: string | undefined;
	const slept = sleep().then((r: string) => (result = r));
	mock.timers.tick(499);
	await new Promise(setImmediate);
	assert.equal(result, undefined);
	mock.timers.tick(1);
	assert.equal(await slept, "Slept 500 ms");
});

test("rejects when aborted", async () => {
	const ac = new AbortController();
	const aborted = sleep(ac.signal);
	ac.abort();
	assert.equal(await aborted, "AbortError");
});
