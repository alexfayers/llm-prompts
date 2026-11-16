import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, describe, test } from "node:test";
import { makeCtx, useEnv } from "./helpers.ts";
import { registerBtw } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/btw.ts";

const user = (id: string) => ({ type: "message", id, message: { role: "user", content: id } });
const assistantCalling = (id: string, ...calls: string[]) => ({ type: "message", id, message: { role: "assistant", content: calls.map((call) => ({ type: "toolCall", id: call })) } });
const result = (id: string, call: string) => ({ type: "message", id, message: { role: "toolResult", toolCallId: call } });

const STUB = path.join(import.meta.dirname, "fixtures/fork-stub.mjs");
const agentDir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-btw-"));
after(() => fs.rmSync(agentDir, { recursive: true }));
useEnv({ PI_CODING_AGENT_DIR: agentDir, PI_CONTEXT_CHILD: undefined });

async function btw(text: string, options: { source?: string } = {}) {
	const handlers: Record<string, any> = {};
	const appended: unknown[][] = [];
	const sent: unknown[] = [];
	registerBtw(
		{
			on: (event: string, handler: unknown) => (handlers[event] = handler),
			appendEntry: (...args: unknown[]) => appended.push(args),
			registerEntryRenderer: () => undefined,
			sendUserMessage: (...args: unknown[]) => sent.push(args),
			getThinkingLevel: () => "low",
		} as any,
		[process.execPath, STUB],
	);
	const branch = [user("u1"), assistantCalling("a1", "c1"), result("r1", "c1"), assistantCalling("a2", "c2")];
	const ctx = makeCtx({ model: { provider: "prov", id: "mod" }, sessionManager: { getBranch: () => branch, getHeader: () => ({ type: "session", id: "main-id" }) } as any });
	const handled = await handlers.input({ text, source: options.source ?? "interactive" }, ctx);
	for (let wait = 0; handled && wait < 500 && !appended.length && !ctx.notices.some(([, level]) => level === "warning"); wait++) await new Promise((resolve) => setTimeout(resolve, 10));
	return { handled, appended, sent, ctx };
}

describe("//btw", () => {
	test("answers on a btw-role copy of the settled session and stores the answer outside the model context", async () => {
		const { handled, appended, sent, ctx } = await btw("//btw STUB_INSPECT");
		assert.deepEqual(handled, { action: "handled" });
		assert.equal(appended.length, 1);
		const [type, data] = appended[0] as [string, { q: string; a: string }];
		assert.equal(type, "pi-context-btw");
		assert.equal(data.q, "STUB_INSPECT");
		const seen = JSON.parse(data.a.replace(/^echo: /, ""));
		assert.deepEqual(seen.handshake, { role: "btw", inherited: "r1" });
		assert.deepEqual(seen.seed.slice(1).map((entry: any) => entry.id), ["u1", "a1", "r1"]);
		assert.match(seen.prompt, /one side question[\s\S]*STUB_INSPECT$/);
		assert.deepEqual(sent, []);
		assert.match(ctx.notices[0][0], /btw/);
	});
});
