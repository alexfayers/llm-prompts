import assert from "node:assert/strict";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { makeEvents } from "./helpers.ts";

async function run(mode: string) {
	const events = makeEvents();
	const handlers: Record<string, ((...args: any[]) => void)[]> = {};
	const extension = join(import.meta.dirname, "../../src/llm_prompts/prompts/pi/extensions/herdr-permission-blocked.ts");
	(await import(pathToFileURL(extension).href)).default({ events, on: (name: string, handler: () => void) => (handlers[name] ??= []).push(handler) });
	handlers.session_start.forEach((handler) => handler({}, { mode }));
	for (const step of ["pa", "pa", "pb", "da", "da", "dc", "db"]) {
		events.emit(step[0] === "p" ? "permissions:ui_prompt" : "permissions:decision", { requestId: step[1] });
	}
	return events.emitted.filter(([name]) => name === "herdr:blocked").map(([, payload]) => payload);
}

test("each prompt blocks once until its own decision", async () => {
	const on = { active: true, label: "Permission prompt" };
	assert.deepEqual(await run("tui"), [on, on, { active: false }, { active: false }]);
});

test("no blocked state is shown without the terminal UI", async () => {
	for (const mode of ["rpc", "json", "print"]) assert.deepEqual(await run(mode), []);
});
