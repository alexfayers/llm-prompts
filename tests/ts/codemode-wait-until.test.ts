import assert from "node:assert/strict";
import { test } from "node:test";
import { loadExtension } from "./helpers.ts";

const ext = await loadExtension("codemode-wait-until");
const run = async (body: string, options = "") => {
	const input = { code: `${options}${body}` };
	await ext.fire("tool_call", { toolName: "codemode", input });
	delete (globalThis as any).waitUntil;
	const slept: number[] = [];
	const tools = { sleep: async ({ ms }: { ms: number }) => void slept.push(ms) };
	const result = await new Function("tools", `return (async()=>{${input.code.replace("// @options:", "//")}})()`)(tools).catch((e: Error) => e.message);
	return { result, slept };
};

test("waitUntil returns the first truthy value", async () => {
	for (const options of ["", "// @options: {}\n"]) {
		const { result, slept } = await run("let n=0;return waitUntil(()=>++n>2&&n,{intervalMs:5});", options);
		assert.deepEqual([result, slept], [3, [5, 5]]);
	}
});

test("waitUntil throws once the timeout passes", async () => {
	const { result } = await run("return waitUntil(()=>false,{intervalMs:10,timeoutMs:5});");
	assert.equal(result, "waitUntil timed out after 5 ms");
});

test("waitUntil sleeps at most the sleep limit", async () => {
	const { slept } = await run("let n=0;return waitUntil(()=>++n>1,{intervalMs:700000});");
	assert.deepEqual(slept, [600000]);
});

test("waitUntil checks once more at the deadline before throwing", async () => {
	const { result, slept } = await run("const end=Date.now()+5;return waitUntil(()=>Date.now()>=end&&'ok',{intervalMs:1000,timeoutMs:5});");
	assert.equal(result, "ok");
	assert.ok(slept.every((ms) => ms <= 5));
});

test("waitUntil is only added where the options line allows", async () => {
	const cases: [string, string, unknown][] = [
		["", '"use strict";return typeof waitUntil+(function(){return this})();', "functionundefined"],
		["\n// @options: {}\n", "return typeof waitUntil;", "undefined"],
	];
	for (const [options, body, expected] of cases) assert.equal((await run(body, options)).result, expected);
});

test("other tools and non-string code are left alone", async () => {
	for (const event of [{ toolName: "bash", input: { code: "x" } }, { toolName: "codemode", input: { code: 1 } }]) {
		const before = structuredClone(event);
		await ext.fire("tool_call", event);
		assert.deepEqual(event, before);
	}
});
