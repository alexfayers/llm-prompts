import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

const entry = (id: string, message: object) => ({ id, type: "message", message });
const call = (id: string, callId: string, name: string, args: object) => entry(id, { role: "assistant", content: [{ type: "toolCall", id: callId, name, arguments: args }] });
const result = (id: string, callId: string, toolName: string, text: string, details?: object) =>
	entry(id, { role: "toolResult", toolCallId: callId, toolName, content: [{ type: "text", text }], details, isError: false });
const stub = (text: string) => ({ role: "toolResult", content: [{ type: "text", text }] });

const BRANCH = [
	entry("u0", { role: "user", content: "start" }),
	call("a1", "c1", "bash", { command: "ls" }),
	result("r1", "c1", "bash", "alpha.txt\nbeta.txt"),
	call("a2", "c2", "read", { path: "x" }),
	result("r2", "c2", "read", "secret needle here"),
	call("a3", "c3", "checkpoint", { action: "rewind", target: "-2" }),
	result("r3", "c3", "checkpoint", "rewinding", { action: "rewind", target: "-2" }),
];

async function load(entries: any[], view: Record<string, object[] | null>) {
	const ext = await loadExtension("transcript");
	const sessionManager = {
		getBranch: () => entries,
		buildSessionProjection: () => ({
			entries: entries.filter((e) => view[e.id] !== null).map((e) => ({ sourceEntry: e, messages: view[e.id] ?? [e.message] })),
		}),
	};
	return { ext, ctx: ext.makeCtx({ sessionManager: sessionManager as any }) };
}

const text = (out: any): string => out.content[0].text;

describe("transcript tool", () => {
	test("with no arguments it indexes the folded, removed and compacted regions", async () => {
		const { ext, ctx } = await load(BRANCH, { u0: null, r1: [stub("[folded: bash]")], a2: [], r2: [] });
		const out = text(await ext.callTool("transcript", {}, ctx));
		assert.match(out, /compacted.*u0/);
		assert.match(out, /folded.*r1.*bash/);
		assert.match(out, /removed.*a2\.\.r2.*read/);
		assert.match(out, /checkpoint "-2"/);
		assert.doesNotMatch(out, /secret needle/);
	});

	test("around shows the raw entries a region replaced, by entry id or checkpoint target", async () => {
		const { ext, ctx } = await load(BRANCH, { a2: [], r2: [] });
		for (const around of ["r2", "-2"]) {
			const out = text(await ext.callTool("transcript", { around }, ctx));
			assert.match(out, /read.*"path":"x"/);
			assert.match(out, /secret needle here/);
			assert.doesNotMatch(out, /alpha/);
		}
		await assert.rejects(ext.callTool("transcript", { around: "nope" }, ctx), /no folded region/);
	});

	test("an invalid pattern returns an error result", async () => {
		const { ext, ctx } = await load(BRANCH, {});
		const out: any = await ext.callTool("transcript", { pattern: "(" }, ctx);
		assert.equal(out.isError, true);
		assert.match(text(out), /Invalid pattern/);
	});
});
