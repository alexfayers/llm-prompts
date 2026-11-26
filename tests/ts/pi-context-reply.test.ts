import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { replyText } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/reply.ts";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-reply-"));
after(() => fs.rmSync(dir, { recursive: true }));
useEnv({ PI_CONTEXT_CHILD: undefined });

async function delegate(role: string) {
	const file = path.join(dir, `${role}.json`);
	fs.writeFileSync(file, JSON.stringify({ role }));
	process.env.PI_CONTEXT_CHILD = file;
	return loadExtension("pi-context/index", { ctx: { cwd: "/main" } });
}

const settle = (ext: Awaited<ReturnType<typeof delegate>>) => ext.fire("agent_before_settle", { outcome: "completed", entries: [], continue: false });

describe("the reply tool", () => {
	test("a reader and a writer get reply, and its result ends the turn with the arguments as details", async () => {
		for (const role of ["reader", "writer"]) {
			const ext = await delegate(role);
			const args = { outcome: "done", ref: "pr-1", text: "report" };
			const result = await ext.callTool("reply", args);
			assert.equal(result.terminate, true);
			assert.deepEqual(result.details, args);
		}
	});

	test("outside a delegate reply returns an error result and the session is not nudged", async () => {
		process.env.PI_CONTEXT_CHILD = "";
		const ext = await loadExtension("pi-context/index");
		const result = await ext.callTool("reply", { outcome: "done", ref: "" });
		assert.deepEqual([result.isError, result.terminate], [true, undefined]);
		assert.match(result.content[0].text, /Only a delegate/);
		assert.equal(await settle(ext), undefined);
	});

	test("a delegate that stops without calling reply is nudged once per prompt", async () => {
		const ext = await delegate("reader");
		const nudge = await settle(ext);
		assert.equal(nudge.continue, true);
		assert.match(nudge.entries[0].content, /Call reply/);
		assert.equal(await settle(ext), undefined);
		await ext.fire("input", { text: "next" });
		assert.equal((await settle(ext)).continue, true);
	});

	test("reply called with other tools in the same message returns an error result and does not end the turn", async () => {
		const ext = await delegate("reader");
		await ext.fire("message_end", { message: { role: "assistant", content: [{ type: "toolCall", name: "read" }, { type: "toolCall", name: "reply" }] } });
		const result = await ext.callTool("reply", { outcome: "done", ref: "" });
		assert.deepEqual([result.isError, result.terminate], [true, undefined]);
		assert.match(result.content[0].text, /alone/);
		await ext.fire("message_end", { message: { role: "assistant", content: [{ type: "toolCall", name: "reply" }] } });
		assert.equal((await ext.callTool("reply", { outcome: "done", ref: "" })).terminate, true);
	});

	test("a delegate whose last text has a valid OUTCOME line is not nudged", async () => {
		const ext = await delegate("writer");
		await ext.fire("message_end", { message: { role: "assistant", content: [{ type: "text", text: "OUTCOME done ref:pr-1" }] } });
		assert.equal(await settle(ext), undefined);
		await ext.fire("input", { text: "next" });
		await ext.fire("message_end", { message: { role: "assistant", content: [{ type: "text", text: "OUTCOME maybe ref:x" }] } });
		assert.equal((await settle(ext)).continue, true);
	});

	test("a delegate that called reply is not nudged", async () => {
		const ext = await delegate("reader");
		await ext.fire("tool_result", { toolName: "reply", isError: false });
		assert.equal(await settle(ext), undefined);
	});
});

describe("replyText", () => {
	test("renders the typed fields as an OUTCOME reply", () => {
		const reply = {
			outcome: "found-it" as const,
			ref: "rc-1",
			notify: true,
			verdict: "FINDINGS" as const,
			findings: [{ severity: "high", location: "a.ts:3", text: "off by one" }],
			asks: ["Which branch?\nmain or dev"],
			denied: ["no access"],
			text: "body",
		};
		assert.equal(replyText(reply), 'OUTCOME found-it notify ref:rc-1\nVerdict: FINDINGS\n- high a.ts:3: off by one\nASK: Which branch? main or dev\nDENIED: "no access"\nbody');
		assert.equal(replyText({ outcome: "done", ref: "" }), "OUTCOME done ref:");
	});
});
