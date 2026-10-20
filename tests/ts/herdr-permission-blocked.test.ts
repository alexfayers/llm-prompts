import assert from "node:assert/strict";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { makeEvents } from "./helpers.ts";

test("each prompt blocks once until its own decision", async () => {
	const events = makeEvents();
	const extension = join(import.meta.dirname, "../../src/llm_prompts/prompts/pi/extensions/herdr-permission-blocked.ts");
	(await import(pathToFileURL(extension).href)).default({ events });
	for (const step of ["pa", "pa", "pb", "da", "da", "dc", "db"]) {
		events.emit(step[0] === "p" ? "permissions:ui_prompt" : "permissions:decision", { requestId: step[1] });
	}
	const on = { active: true, label: "Permission prompt" };
	const blocked = events.emitted.filter(([name]) => name === "herdr:blocked").map(([, payload]) => payload);
	assert.deepEqual(blocked, [on, on, { active: false }, { active: false }]);
});
