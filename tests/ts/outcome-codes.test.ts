import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";
import { parseOutcome } from "../../src/llm_prompts/prompts/pi/extensions/outcome-codes.ts";

const RESULT_TYPE = "pi-herdsman-agent-result";
const system = { role: "system", content: "base", sections: {}, timestamp: 0 };
const head = ["Agent result · agent=a · definition=worker · status=completed", "Result ref: result:a#1", 'To continue this session, use continue_agent with session="result:a#1".'];
const result = (...body: string[]) => ({ role: "custom", customType: RESULT_TYPE, content: [...head, ...body].join("\n\n"), display: true, timestamp: 1 });
const project = async (message: unknown) => {
	const ext = await loadExtension("outcome-codes");
	const out: any = await ext.fire("context_with_system", { messages: [system, message] });
	return out?.messages[1].content as string | undefined;
};

describe("handler", () => {
	test("context_with_system reduces a coded result to its header and OUTCOME line", async () => {
		const text = await project(result("OUTCOME done ref:result:a#1\nLong report line one.\nLong report line two."));
		assert.equal(text, [...head, "OUTCOME done ref:result:a#1"].join("\n"));
	});

	test("found-it keeps a short next line and drops a long one", async () => {
		const code = "OUTCOME found-it ref:result:a#1";
		assert.equal(await project(result(`${code}\n\nsrc/a.ts:12\nmore`)), [...head, code, "src/a.ts:12"].join("\n"));
		assert.equal(await project(result(`${code}\n${"x".repeat(201)}`)), [...head, code].join("\n"));
	});

	test("ASK, DENIED and delegation status lines are kept", async () => {
		const code = "OUTCOME blocked-on-user ref:result:a#1";
		const ask = "ASK: use A or B?";
		const denied = 'DENIED: "no"';
		const status = "Delegation status: 0 active direct agents; 0 pending direct results; all direct agent assignments are resolved.";
		const text = await project(result(`${code}\ndetails\n${ask}\nmore\n${denied}`, status));
		assert.equal(text, [...head, code, ask, denied, status].join("\n"));
	});
});

describe("parseOutcome", () => {
	test("reads the code, the notify flag and the ref from the OUTCOME line anywhere in the text", () => {
		assert.deepEqual(parseOutcome("body\nOUTCOME blocked-on-user notify ref:rc-fork-x\nASK: q?"), { code: "blocked-on-user", notify: true, ref: "rc-fork-x" });
		assert.deepEqual(parseOutcome("OUTCOME maybe"), { code: "maybe", notify: false, ref: undefined });
		assert.equal(parseOutcome("no code here"), undefined);
	});
});
