import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

const GUIDANCE_TYPE = "pi-herdsman-delegation-guidance";
const system = { role: "system", content: "base", sections: {}, timestamp: 0 };
const guidance = (timestamp: number, customType = GUIDANCE_TYPE) => ({ role: "custom", customType, content: "g", display: false, timestamp });
const user = (timestamp: number) => ({ role: "user", content: "hi", timestamp });

describe("handler", () => {
	test("context_with_system keeps only the first guidance message", async () => {
		const ext = await loadExtension("herdsman-guidance-dedupe");
		const [first, second] = [guidance(2), guidance(4)];
		const messages = [system, first, user(3), second, guidance(5, "other")];
		const out = await ext.fire("context_with_system", { messages });
		assert.deepEqual(out.messages, [system, first, user(3), messages[4]]);
	});

	test("context_with_system leaves a list without a repeat alone", async () => {
		const ext = await loadExtension("herdsman-guidance-dedupe");
		const out = await ext.fire("context_with_system", { messages: [system, guidance(1), user(2), guidance(3, "other")] });
		assert.equal(out, undefined);
	});
});
