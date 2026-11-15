import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { receipt as readReceipt } from "../../src/llm_prompts/prompts/pi/extensions/already-seen.ts";

type Raw = { id: string; type: string; message?: any; customType?: string; data?: any };
const entry = (id: string, message: object): Raw => ({ id, type: "message", message });
const user = (id: string) => entry(id, { role: "user", content: "go" });
const assistant = (id: string, ...content: object[]) => entry(id, { role: "assistant", content });
const aborted = (id: string, ...content: object[]) => entry(id, { role: "assistant", content, stopReason: "aborted" });
const call = (id: string, name = "bash", args: object = { command: "ls" }) => ({ type: "toolCall", id, name, arguments: args });
const text = (value: string) => ({ type: "text", text: value });
const thinking = (value: string) => ({ type: "thinking", thinking: value });
const result = (id: string, callId: string, toolName: string, body: string, extra: object = {}) =>
	entry(id, { role: "toolResult", toolCallId: callId, toolName, content: [text(body)], isError: false, ...extra });
const BIG = "x".repeat(4000);

/** Projection of the raw entries, with an edit replacing an entry's content or (null) omitting it. */
const project = (entries: Raw[], edits: Record<string, object[] | null> = {}) =>
	entries.map((sourceEntry) => ({ sourceEntry, messages: edits[sourceEntry.id] === null ? [] : [{ ...sourceEntry.message, ...(edits[sourceEntry.id] ? { content: edits[sourceEntry.id] } : {}) }] }));

useEnv({ CONTEXT_FOLD: "on", CONTEXT_FOLD_PENDING_TOKENS: "100", CONTEXT_FOLD_KEEP_TOKENS: "1500", PI_CONTEXT_CHILD: undefined });

async function settle(entries: Raw[], { edits = {}, outcome = "completed", branch = entries, proposed = [] as object[], errorMessage = "", loaded = undefined as Awaited<ReturnType<typeof loadExtension>> | undefined } = {}) {
	const ext = loaded ?? (await loadExtension("context-fold"));
	const ctx = ext.makeCtx({ sessionManager: { getBranch: () => branch } as any });
	const contextMessages = errorMessage ? [{ role: "assistant", stopReason: "error", errorMessage }] : [];
	const out = await ext.fire("agent_before_settle", { outcome, entries: proposed, continue: false, context: { contextEntries: project(entries, edits), contextMessages } }, ctx);
	return { ext, ctx, out, added: (out?.entries ?? []).slice(proposed.length) as any[] };
}

const OLD_RESULTS = [user("u0"), assistant("a1", call("c1")), result("r1", "c1", "bash", BIG), assistant("a2", call("c2")), result("r2", "c2", "bash", BIG), assistant("a3", text("done"))];

describe("agent_before_settle", () => {
	test("a long result before the newest part of the context is replaced by a stub whose full text result_fetch can read", async () => {
		const { added } = await settle(OLD_RESULTS);
		const edit = added.find((draft) => draft.type === "context_edit");
		assert.equal(edit.targetId, "r1");
		assert.equal(edit.replacement.content[0].text, '[folded: bash {"command":"ls"} -> 4000 chars; result_fetch({ref:"fold-c1"}) resends it]');
		assert.deepEqual(added.find((draft) => draft.customType === "result-cap").data, { ref: "fold-c1", text: BIG });
		assert.deepEqual(added.find((draft) => draft.customType === "context-fold").data.targets, ["r1"]);
		assert.equal(added.filter((draft) => draft.type === "context_edit").length, 1);
	});

	test("results that must stay are never folded", async () => {
		const exempt = ["checkpoint", "asks", "ask_user", "compact_now", "fork", "reload_now"];
		const old = [
			user("u0"),
			assistant("a1", call("c1")),
			result("r1", "c1", "bash", BIG, { isError: true }),
			assistant("a2", call("c2")),
			result("r2", "c2", "bash", `${BIG}\nASK: which one?`),
			assistant("a3", call("c3")),
			result("r3", "c3", "bash", `${BIG}\nDENIED: "no"`),
			assistant("a4", call("c4")),
			result("r4", "c4", "bash", "short"),
			assistant("a5", call("c5")),
			result("r5", "c5", "bash", BIG),
			...exempt.flatMap((name, index) => [assistant(`ae${index}`, call(`ce${index}`, name)), result(`re${index}`, `ce${index}`, name, BIG)]),
		];
		const recent = [assistant("a9", call("c9")), result("r9", "c9", "bash", BIG), assistant("a10", text("done"))];
		const { added } = await settle([...old, ...recent], { edits: { r5: [text("[folded already]")] } });
		assert.deepEqual(added.find((draft) => draft.customType === "context-fold")?.data.targets ?? [], []);
	});

	test("thinking is stripped from the earliest folded result onward and kept before it", async () => {
		const entries = [
			user("u0"),
			assistant("a0", thinking("early"), call("c0")),
			result("r0", "c0", "bash", "short"),
			assistant("a1", thinking("before"), call("c1")),
			result("r1", "c1", "bash", BIG),
			assistant("a2", thinking("after"), text("note"), call("c2")),
			result("r2", "c2", "bash", BIG),
			assistant("a3", thinking("only")),
			assistant("a4", text("done")),
		];
		const { added } = await settle(entries);
		const edits = Object.fromEntries(added.filter((draft) => draft.type === "context_edit").map((draft) => [draft.targetId, draft.replacement.content]));
		assert.deepEqual(Object.keys(edits).sort(), ["a2", "a3", "r1"]);
		assert.deepEqual(edits.a2, [text("note"), call("c2")]);
		assert.equal(edits.a3[0].type, "text");
	});

	test("a capped result is stubbed with its own ref and a folded one is fetched back byte for byte", async () => {
		const full = "y".repeat(20000);
		const capped = { id: "k1", type: "custom", customType: "result-cap", data: { ref: "rc-c1", text: full } };
		const entries = [user("u0"), assistant("a1", call("c1")), result("r1", "c1", "bash", BIG), assistant("a2", call("c2")), result("r2", "c2", "bash", BIG), assistant("a3", text("done"))];
		const { added } = await settle(entries, { branch: [capped, ...entries] as Raw[] });
		assert.equal(added.find((draft) => draft.type === "context_edit").replacement.content[0].text, '[folded: bash {"command":"ls"} -> 20000 chars; result_fetch({ref:"rc-c1"}) resends it]');
		assert.equal(added.filter((draft) => draft.customType === "result-cap").length, 0);

		const fresh = (await settle(OLD_RESULTS)).added.find((draft) => draft.customType === "result-cap");
		const fetcher = await loadExtension("result-cap");
		const ctx = fetcher.makeCtx({ sessionManager: { getBranch: () => [{ id: "k2", type: "custom", ...fresh }] } as any });
		assert.equal((await fetcher.callTool("result_fetch", { ref: "fold-c1", limit: 10000 }, ctx)).content[0].text, BIG);
	});

	test("a receipt that points at a folded result names its ref", async () => {
		const entries = [
			user("u0"),
			assistant("a1", call("c1", "read", { path: "a.ts" })),
			result("r1", "c1", "read", BIG),
			assistant("a2", call("c2", "read", { path: "a.ts" })),
			result("r2", "c2", "read", readReceipt("r1")),
			assistant("a3", call("c3")),
			result("r3", "c3", "bash", BIG),
			assistant("a4", text("done")),
		];
		const { added } = await settle(entries);
		const receipt = added.find((draft) => draft.targetId === "r2");
		assert.equal(receipt.replacement.content[0].text, 'unchanged since entry r1, whose result was folded; result_fetch({ref:"fold-c1"}) resends it');
	});

	test("a fold is proposed only for a completed run that saves enough, keeps earlier proposals and tells the user", async () => {
		const proposed = [{ type: "custom", customType: "other", data: 1 }];
		const { out, added, ctx } = await settle(OLD_RESULTS, { proposed });
		assert.deepEqual(out.entries[0], proposed[0]);
		assert.equal(added.at(-1).data.trigger, "run-end");
		assert.match(ctx.notices[0][0], /folded 1 old tool result.*saves ~\d+ tokens/);
		for (const outcome of ["aborted", "error"]) assert.equal((await settle(OLD_RESULTS, { outcome })).out, undefined);
		process.env.CONTEXT_FOLD_PENDING_TOKENS = "100000";
		assert.equal((await settle(OLD_RESULTS)).out, undefined);
	});

	test("dry only records the plan, folding is on by default, off does nothing, and a delegated session does not load the extension", async () => {
		process.env.CONTEXT_FOLD = "dry";
		const { added } = await settle(OLD_RESULTS);
		assert.deepEqual(added.map((draft) => draft.type), ["custom"]);
		assert.deepEqual(added[0].data.targets, ["r1"]);
		delete process.env.CONTEXT_FOLD;
		assert.equal((await settle(OLD_RESULTS)).added.filter((draft) => draft.type === "context_edit").length, 1);
		process.env.CONTEXT_FOLD = "off";
		assert.equal((await settle(OLD_RESULTS)).out, undefined);
		process.env.CONTEXT_FOLD = "on";
		process.env.PI_CONTEXT_CHILD = "/tmp/handshake.json";
		assert.deepEqual((await loadExtension("context-fold")).handlers, {});
	});

	test("a rejected request right after a fold restores the folded entries, stops folding and says why", async () => {
		const first = await settle(OLD_RESULTS);
		const folded = first.added.filter((draft) => draft.type === "context_edit").map((draft) => [draft.targetId, draft.replacement.content]);
		const edits = Object.fromEntries(folded);
		const { added, ctx, ext } = await settle(OLD_RESULTS, { loaded: first.ext, edits, outcome: "error", errorMessage: `400 bad request ${"!".repeat(300)}` });
		assert.deepEqual(added.filter((draft) => draft.type === "context_edit").map((draft) => [draft.targetId, draft.replacement.content]), [["r1", [text(BIG)]]]);
		assert.equal(added.at(-1).data.trigger, "revert");
		assert.match(ctx.notices[0][0], /^context-fold: reverted .*400 bad request !+$/);
		assert.ok(ctx.notices[0][0].length < 400);
		assert.equal((await settle(OLD_RESULTS, { loaded: ext })).out, undefined);
	});

	test("an error with no fold before it, or after a completed turn, changes nothing", async () => {
		assert.equal((await settle(OLD_RESULTS, { outcome: "error" })).out, undefined);
		const { ext, ctx } = await settle(OLD_RESULTS);
		await ext.fire("turn_end", { outcome: "completed", entries: [] }, ctx);
		assert.equal((await settle(OLD_RESULTS, { loaded: ext, outcome: "error" })).out, undefined);
	});

	test("an entry another extension already proposed to edit is left to it", async () => {
		const proposed = [{ type: "context_edit", targetId: "r1", replacement: null }, { type: "context_edit", targetId: "a2", replacement: { content: [text("x")] } }];
		const entries = [user("u0"), assistant("a1", call("c1")), result("r1", "c1", "bash", BIG), assistant("a2", thinking("t"), call("c2")), result("r2", "c2", "bash", BIG), assistant("a3", text("done"))];
		const { added } = await settle(entries, { proposed });
		assert.deepEqual(added.filter((draft) => draft.targetId === "r1" || draft.targetId === "a2"), []);
	});

	test("a thinking signature counts toward neither the newest-context window nor the saving", async () => {
		const signed = { type: "thinking", thinking: "t", thinkingSignature: "S".repeat(40000) };
		const entries = [user("u0"), assistant("a1", call("c1")), result("r1", "c1", "bash", BIG), assistant("a2", signed, call("c2")), result("r2", "c2", "bash", BIG), assistant("a3", signed, text("done"))];
		const { added } = await settle(entries);
		assert.deepEqual(added.find((draft) => draft.customType === "context-fold").data.targets, ["r1"]);
		assert.ok(added.find((draft) => draft.customType === "context-fold").data.savedTokens < 1100);
	});

	test("an aborted turn before the newest context becomes one line that lists the refs of its results", async () => {
		const entries = [
			user("u0"),
			aborted("a1", thinking("hmm"), call("c1", "bash", { command: "make" }), call("c2", "bash", { command: "sleep 99" })),
			result("r1", "c1", "bash", BIG),
			result("r2", "c2", "bash", "Tool execution was aborted", { isError: true }),
			user("u1"),
			assistant("a2", thinking("later"), call("c3")),
			result("r3", "c3", "bash", BIG + BIG),
			assistant("a3", text("done")),
		];
		const { added } = await settle(entries);
		const edits = Object.fromEntries(added.filter((draft) => draft.type === "context_edit").map((draft) => [draft.targetId, draft.replacement]));
		assert.equal(edits.a1.content[0].text, '[abandoned turn: bash {"command":"make"}: done, bash {"command":"sleep 99"}: aborted; result_fetch refs: fold-c1, fold-c2]');
		assert.deepEqual([edits.r1, edits.r2], [null, null]);
		assert.deepEqual(added.filter((draft) => draft.customType === "result-cap" && draft.data.ref !== "fold-c3").map((draft) => draft.data), [{ ref: "fold-c1", text: BIG }, { ref: "fold-c2", text: "Tool execution was aborted" }]);
		assert.ok(edits.a2.content.every((block: any) => block.type !== "thinking"));
		assert.equal(added.filter((draft) => draft.targetId === "r1").length, 1);
	});

	test("aborted turns that hold a handoff line or edited result, the last assistant message and text-only aborted messages are handled safely", async () => {
		const huge = entry("uh", { role: "user", content: "y".repeat(8000) });
		const entries = [
			user("u0"),
			aborted("a1", call("c1")),
			result("r1", "c1", "bash", `${BIG}\nASK: which one?`),
			aborted("a2", call("c2")),
			result("r2", "c2", "bash", `DENIED: "no"`),
			aborted("a3", call("c3")),
			result("r3", "c3", "bash", "ran"),
			aborted("a4", thinking("hm"), text("I was going to check the config file and then edit it")),
			aborted("a5", call("c5")),
			result("r5", "c5", "bash", BIG),
			aborted("a6", call("c6")),
			result("r6", "c6", "bash", BIG),
			huge,
		];
		const { added } = await settle(entries, { edits: { r3: [text("[folded already]")] } });
		const edits = Object.fromEntries(added.filter((draft) => draft.type === "context_edit").map((draft) => [draft.targetId, draft.replacement]));
		assert.deepEqual(Object.keys(edits).sort(), ["a4", "a5", "r5", "r6"]);
		assert.equal(edits.a4.content[0].text, "[abandoned: I was going to check the config file and then edit it]");
	});

	test("an aborted turn inside the newest context stays", async () => {
		const entries = [user("u0"), aborted("a1", call("c1")), result("r1", "c1", "bash", "Tool execution was aborted", { isError: true }), assistant("a2", text("done"))];
		const { out } = await settle(entries);
		assert.equal(out, undefined);
	});
});
