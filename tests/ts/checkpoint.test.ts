import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

type Details = Record<string, unknown>;
const entry = (id: string, message: object) => ({ id, type: "message", message });
const call = (id: string, ...calls: [string, string, object][]) =>
	entry(id, { role: "assistant", content: calls.map(([callId, name, args]) => ({ type: "toolCall", id: callId, name, arguments: args })) });
const result = (id: string, callId: string, toolName: string, text: string, details?: Details) =>
	entry(id, { role: "toolResult", toolCallId: callId, toolName, content: [{ type: "text", text }], details, isError: false });
const mark = (id: string, callId: string, name: string) => result(id, callId, "checkpoint", `marked ${name}`, { action: "mark", name });
const rewindResult = (id: string, callId: string, target: string, mode = "summary") =>
	result(id, callId, "checkpoint", "rewinding", { action: "rewind", target, mode, summary: "S" });
const fold = (id: string, text: string) => ({ id, type: "custom_message", message: { role: "custom", customType: "checkpoint-fold", content: text } });

async function load(entries: any[], omitted: string[] = [], shape?: string) {
	const ext = await loadExtension("checkpoint", { pi: { getSettings: () => ({ llmPrompts: { checkpoint: { shape } } }) } });
	const sessionManager = {
		getBranch: () => entries,
		buildSessionProjection: () => ({ entries: entries.map((e) => ({ sourceEntry: e, messages: omitted.includes(e.id) ? [] : [e.message] })) }),
	};
	return { ext, ctx: ext.makeCtx({ sessionManager: sessionManager as any }) };
}

async function endTurn(ext: any, ctx: any, rewind: any, turn: { messageEntryId: string; resultIds: string[]; results?: any[] }) {
	const toolResults = turn.results ?? [rewind.message];
	return ext.fire("turn_end", { toolResults, toolResultEntryIds: turn.resultIds, messageEntryId: turn.messageEntryId, entries: [] }, ctx);
}

const nulled = (out: any) => out.entries.filter((e: any) => e.replacement === null).map((e: any) => e.targetId);
const TWO_MARKS = [
	entry("u0", { role: "user", content: "go" }),
	call("a1", ["c1", "checkpoint", { action: "mark" }]),
	mark("r1", "c1", "a"),
	call("a2", ["c2", "read", { path: "x" }]),
	result("r2", "c2", "read", "file text"),
	call("a3", ["c3", "checkpoint", { action: "mark" }]),
	mark("r3", "c3", "b"),
	call("a4", ["c4", "read", { path: "y" }]),
	result("r4", "c4", "read", "other text"),
	call("a5", ["c5", "checkpoint", { action: "rewind" }]),
];

describe("checkpoint tool", () => {
	test("marks get default names that skip visible ones, and a duplicate name errors", async () => {
		const { ext, ctx } = await load([]);
		assert.match((await ext.callTool("checkpoint", { action: "mark" }, ctx)).content[0].text, /"m1" marked/);
		const withMark = await load([call("a1", ["c1", "checkpoint", {}]), mark("r1", "c1", "m1")]);
		assert.match((await withMark.ext.callTool("checkpoint", { action: "mark" }, withMark.ctx)).content[0].text, /"m2" marked \(marks: m1, m2\)/);
		await assert.rejects(withMark.ext.callTool("checkpoint", { action: "mark", name: "m1" }, withMark.ctx), /exists/);
	});

	test("a rewind defaults to the latest mark and rejects unknown or folded marks", async () => {
		const { ext, ctx } = await load(TWO_MARKS, ["r3"]);
		assert.equal((await ext.callTool("checkpoint", { action: "rewind", summary: "s" }, ctx)).details.target, "a");
		await assert.rejects(ext.callTool("checkpoint", { action: "rewind", target: "b", summary: "s" }, ctx), /unknown checkpoint "b".*a/);
		await assert.rejects(load([]).then(({ ext, ctx }) => ext.callTool("checkpoint", { action: "rewind", summary: "s" }, ctx)), /call mark first/);
		await assert.rejects(ext.callTool("checkpoint", { action: "rewind" }, ctx), /needs a summary/);
	});

	test("marks run one at a time so parallel marks cannot share a name", async () => {
		const { ext } = await load([]);
		assert.equal(ext.tools.checkpoint.executionMode, "sequential");
	});

	test("an error result is never folded", async () => {
		const { ext, ctx } = await load([...TWO_MARKS, rewindResult("r5", "c5", "a")]);
		const failed = { ...(rewindResult("r5", "c5", "a").message as object), isError: true };
		assert.equal(await endTurn(ext, ctx, { message: failed }, { messageEntryId: "a5", resultIds: ["r5"] }), undefined);
	});
});

describe("folding to the first of two marks", () => {
	const fixture = (shape?: string) => load([...TWO_MARKS, rewindResult("r5", "c5", "a")], [], shape);

	test("separate shape omits everything after the target and adds a fold message", async () => {
		const { ext, ctx } = await fixture();
		const out = await endTurn(ext, ctx, rewindResult("r5", "c5", "a"), { messageEntryId: "a5", resultIds: ["r5"] });
		assert.deepEqual(nulled(out), ["a2", "r2", "a3", "r3", "a4", "r4", "a5", "r5"]);
		assert.match(out.entries.at(-1).content, /to "a"\] The steps since mark "a" were run.*Their outcome:\nS\n\nMarks removed with them: b\.\n\nKeep using checkpoints: mark before a detour, rewind after it\.$/s);
		assert.equal(out.entries.at(-1).type, "custom_message");
	});

	test("result shape keeps the rewind turn and puts the fold in its result", async () => {
		const { ext, ctx } = await fixture("result");
		const out = await endTurn(ext, ctx, rewindResult("r5", "c5", "a"), { messageEntryId: "a5", resultIds: ["r5"] });
		assert.deepEqual(nulled(out), ["a2", "r2", "a3", "r3", "a4", "r4"]);
		assert.equal(out.entries.at(-1).targetId, "r5");
		assert.match(out.entries.at(-1).replacement.content[0].text, /to "a"\] The steps since mark "a" were run.*Marks removed with them: b.*Keep using checkpoints/s);
	});
});

test("the fold names no removed marks when there are none", async () => {
	const entries = [call("a1", ["c1", "checkpoint", {}]), mark("r1", "c1", "a"), call("a2", ["c2", "checkpoint", {}]), rewindResult("r2", "c2", "a")];
	const { ext, ctx } = await load(entries);
	const out = await endTurn(ext, ctx, entries[3], { messageEntryId: "a2", resultIds: ["r2"] });
	assert.doesNotMatch(out.entries.at(-1).content, /Marks removed/);
	assert.match(out.entries.at(-1).content, /Their outcome:\nS\n\nKeep using checkpoints/);
});

test("a rewind whose mark turn is missing from the context changes nothing", async () => {
	const entries = [mark("r1", "c1", "a"), call("a2", ["c2", "checkpoint", {}]), rewindResult("r2", "c2", "a")];
	const { ext, ctx } = await load(entries);
	assert.equal(await endTurn(ext, ctx, entries[2], { messageEntryId: "a2", resultIds: ["r2"] }), undefined);
});

test("a raw fold in separate mode keeps the result of a tool called beside the rewind", async () => {
	const entries = [
		call("a1", ["c1", "checkpoint", {}]),
		mark("r1", "c1", "a"),
		call("a2", ["c2", "checkpoint", {}], ["c2b", "read", { path: "w" }]),
		rewindResult("r2", "c2", "a", "raw"),
		result("r2b", "c2b", "read", "BESIDE RAW"),
	];
	const { ext, ctx } = await load(entries);
	const out = await endTurn(ext, ctx, entries[3], { messageEntryId: "a2", resultIds: ["r2", "r2b"], results: [entries[3].message, entries[4].message] });
	assert.match(out.entries.at(-1).content, /\[read \{"path":"w"\}\]\nBESIDE RAW/);
	assert.doesNotMatch(out.entries.at(-1).content, /rewinding/);
	assert.deepEqual(nulled(out), ["a2", "r2", "r2b"]);
});

test("a sibling call in the mark turn stays on the kept side of the boundary", async () => {
	const entries = [
		call("a1", ["c1", "checkpoint", {}], ["c1b", "read", { path: "z" }]),
		mark("r1", "c1", "a"),
		result("r1b", "c1b", "read", "sibling"),
		call("a2", ["c2", "checkpoint", {}], ["c2b", "read", { path: "w" }]),
		rewindResult("r2", "c2", "a"),
		result("r2b", "c2b", "read", "rewind sibling"),
	];
	const { ext, ctx } = await load(entries, [], "result");
	const out = await endTurn(ext, ctx, entries[4], { messageEntryId: "a2", resultIds: ["r2", "r2b"], results: [entries[4].message, entries[5].message] });
	assert.deepEqual(nulled(out), []);
	assert.equal(out.entries.at(-1).targetId, "r2");
});

test("a raw fold keeps an earlier fold's text and not its omitted raw results", async () => {
	const entries = [
		call("a1", ["c1", "checkpoint", {}]),
		mark("r1", "c1", "a"),
		call("a2", ["c2", "read", { path: "x" }]),
		result("r2", "c2", "read", "INNER RAW"),
		fold("f1", "INNER FOLD"),
		call("a3", ["c3", "read", { path: "y" }]),
		result("r3", "c3", "read", "OUTER RAW"),
		call("a4", ["c4", "checkpoint", {}]),
		rewindResult("r4", "c4", "a", "raw"),
	];
	const { ext, ctx } = await load(entries, ["a2", "r2"]);
	const out = await endTurn(ext, ctx, entries[8], { messageEntryId: "a4", resultIds: ["r4"] });
	const content = out.entries.at(-1).content;
	assert.match(content, /INNER FOLD[\s\S]*OUTER RAW/);
	assert.doesNotMatch(content, /INNER RAW|rewinding/);
	assert.deepEqual(nulled(out), ["f1", "a3", "r3", "a4", "r4"]);
});

describe("rewinding to a tool call", () => {
	const CALLS = [
		entry("u0", { role: "user", content: "go" }),
		call("a1", ["c1", "bash", { command: "ls" }]),
		result("r1", "c1", "bash", "files"),
		call("a2", ["c2", "read", { path: "x" }]),
		result("r2", "c2", "read", "x text"),
		call("a3", ["c3", "bash", { command: "pwd" }]),
		result("r3", "c3", "bash", "/"),
		call("a4", ["c4", "checkpoint", { action: "rewind" }]),
	];
	const rewind = (ext: any, ctx: any, target?: string) =>
		ext.tools.checkpoint.execute("c4", { action: "rewind", target, summary: "S" }, undefined, undefined, ctx);
	const foldTo = async (target: string) => {
		const entries = [...CALLS, rewindResult("r4", "c4", target)];
		const { ext, ctx } = await load(entries);
		return endTurn(ext, ctx, entries.at(-1), { messageEntryId: "a4", resultIds: ["r4"] });
	};

	test("-N and <tool>#<n> pick a call counting back, without a mark", async () => {
		const { ext, ctx } = await load(CALLS);
		assert.equal((await rewind(ext, ctx, "-2")).details.target, "-2");
		assert.equal((await rewind(ext, ctx, "bash#2")).details.target, "bash#2");
	});

	test("a call target keeps that call and folds everything after it", async () => {
		assert.deepEqual(nulled(await foldTo("-2")), ["a3", "r3", "a4", "r4"]);
		const out = await foldTo("bash#2");
		assert.deepEqual(nulled(out), ["a2", "r2", "a3", "r3", "a4", "r4"]);
		assert.match(out.entries.at(-1).content, /to "bash#2"\] The steps since call "bash#2" were run/);
	});

	test("a system-prompt update entry in the region is kept, not nulled", async () => {
		const entries = [...CALLS.slice(0, 5), entry("s1", { role: "system", content: "", toolsAdded: [] }), ...CALLS.slice(5), rewindResult("r4", "c4", "-2")];
		const { ext, ctx } = await load(entries);
		const out = await endTurn(ext, ctx, entries.at(-1), { messageEntryId: "a4", resultIds: ["r4"] });
		assert.deepEqual(nulled(out), ["a3", "r3", "a4", "r4"]);
	});

	test("an unknown target lists the forms and the recent calls, and no marks gives a clear error", async () => {
		const { ext, ctx } = await load(CALLS);
		await assert.rejects(rewind(ext, ctx, "-9"), /-N.*<tool>#<n>[\s\S]*-1 bash \{"command":"pwd"\}[\s\S]*-3 bash/);
		await assert.rejects(rewind(ext, ctx, "read#2"), /unknown checkpoint "read#2"/);
		await assert.rejects(rewind(ext, ctx), /no marks/);
	});
});

test("a rewind keeps a user message sent after the target in context, in summary and raw mode", async () => {
	const entries = [...TWO_MARKS.slice(0, 3), entry("u1", { role: "user", content: "also answer this" }), ...TWO_MARKS.slice(3), rewindResult("r5", "c5", "a")];
	const { ext, ctx } = await load(entries);
	const out = await endTurn(ext, ctx, rewindResult("r5", "c5", "a"), { messageEntryId: "a5", resultIds: ["r5"] });
	assert.ok(!nulled(out).includes("u1"));
	assert.ok(nulled(out).includes("r2"));
	const raw = await load(entries.map((e) => (e.id === "r5" ? rewindResult("r5", "c5", "a", "raw") : e)));
	const rawOut = await endTurn(raw.ext, raw.ctx, rewindResult("r5", "c5", "a", "raw"), { messageEntryId: "a5", resultIds: ["r5"] });
	assert.ok(!nulled(rawOut).includes("u1"));
});


const sized = (tokens: number, toolName = "bash") => ({ toolCallId: "c", toolName, input: {}, content: [{ type: "text", text: "x".repeat(tokens * 4) }], isError: false });
const nudged = (out: any) => out?.content?.some((block: { text?: string }) => block.text?.startsWith("[checkpoint]")) ?? false;

describe("checkpoint nudge", () => {
	useEnv({ PI_CONTEXT_CHILD: undefined, PI_HERDSMAN_MAILBOX: undefined });

	test("nudges each time another threshold of result tokens builds up since the user message, keeps the result, gives the advice only in the first nudge, and resets on a checkpoint call or a new run", async () => {
		const ext = await loadExtension("checkpoint", { pi: { getSettings: () => ({ llmPrompts: { checkpoint: { nudgeTokens: 1000 } } }) } });
		await ext.fire("agent_start");
		const outs = [];
		for (let i = 0; i < 8; i++) outs.push(await ext.fire("tool_result", sized(400)));
		assert.deepEqual(outs.map(nudged), [false, false, true, false, false, true, false, false]);
		assert.equal(outs[2].content[0].text.length, 1600);
		assert.match(outs[2].content[1].text, /3 calls, ~1K tokens since the last user message.*checkpoint rewind to the call before it, or to a mark set before it, with a summary/);
		assert.equal(outs[5].content[1].text, "[checkpoint] 6 calls, ~2K tokens since the last user message.");

		await ext.fire("tool_result", sized(0, "checkpoint"));
		assert.equal(nudged(await ext.fire("tool_result", sized(900))), false);
		await ext.fire("agent_start");
		assert.equal(nudged(await ext.fire("tool_result", sized(900))), false);
		assert.match((await ext.fire("tool_result", sized(100))).content[1].text, /checkpoint rewind to the call before it/);
	});
});

test("loading reads no settings, because pi refuses action calls during load", async () => {
	const getSettings = () => {
		throw new Error("Extension runtime not initialized");
	};
	await loadExtension("checkpoint", { pi: { getSettings } });
});
