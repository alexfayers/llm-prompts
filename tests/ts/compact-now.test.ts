import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

const entry = (id: string, type = "message", role = "user") => ({ id, type, message: { role } });
const turnEnd = { toolResults: [{ toolName: "compact_now" }], toolResultEntryIds: ["result"] };

const compactRequest = async (instructions = "summary") => {
	const compacts: { customInstructions: string }[] = [];
	const ext = await loadExtension("compact-now", {
		ctx: { compact: (options: any) => (compacts.push(options), options.onComplete()) },
	});
	await ext.callTool("compact_now", { instructions });
	return { ext, compacts };
};

const beforeCompact = (ext: any, branchEntries: any[], firstKeptEntryId: string) =>
	ext.fire("session_before_compact", {
		customInstructions: "summary",
		branchEntries,
		preparation: { firstKeptEntryId, tokensBefore: 7 },
	});

describe("compact_now", () => {
	test("compacts at the end of the turn that called it, then continues", async () => {
		const { ext, compacts } = await compactRequest();
		assert.equal(compacts.length, 0);
		await ext.fire("turn_end", turnEnd);
		await ext.fire("turn_end", turnEnd);
		assert.deepEqual(compacts.map((options) => options.customInstructions), ["summary"]);
		assert.equal(ext.pi.sent.length, 1);
	});

	test("compacts before any queued follow-up runs, without waiting for the settle", async () => {
		const { ext, compacts } = await compactRequest();
		ext.pi.sendUserMessage("fork result", { deliverAs: "followUp" });
		await ext.fire("turn_end", turnEnd);
		assert.equal(compacts.length, 1);
		assert.deepEqual(ext.pi.sent[0], ["fork result", { deliverAs: "followUp" }]);
		assert.equal(ext.pi.sent.length, 2);
	});

	test("ignores a turn that did not call it", async () => {
		const { ext, compacts } = await compactRequest();
		await ext.fire("turn_end", { toolResults: [{ toolName: "bash" }], toolResultEntryIds: ["other"] });
		assert.equal(compacts.length, 0);
	});

	test("keeps the entries after the tool result in context", async () => {
		const { ext } = await compactRequest();
		await ext.fire("turn_end", turnEnd);
		const branch = [entry("old"), entry("call", "message", "assistant"), entry("result", "message", "toolResult"), entry("late"), entry("later")];
		const result = await beforeCompact(ext, branch, "old");
		assert.equal(result.compaction.firstKeptEntryId, "late");
		assert.equal(result.compaction.summary, "summary");
	});

	test("keeps every entry that arrived after the call when compaction runs much later", async () => {
		const { ext } = await compactRequest();
		await ext.fire("turn_end", turnEnd);
		const late = Array.from({ length: 50 }, (_, index) => entry(`late-${index}`));
		const branch = [entry("old"), entry("result", "message", "toolResult"), ...late];
		const result = await beforeCompact(ext, branch, "old");
		assert.equal(result.compaction.firstKeptEntryId, "late-0");
	});

	test("keeps the default cut when the tool result is not on the branch", async () => {
		const { ext } = await compactRequest();
		await ext.fire("turn_end", turnEnd);
		const result = await beforeCompact(ext, [entry("old"), entry("other")], "other");
		assert.equal(result.compaction.firstKeptEntryId, "other");
	});

	test("keeps the default cut when nothing follows the tool result", async () => {
		const { ext } = await compactRequest();
		await ext.fire("turn_end", turnEnd);
		const branch = [entry("old"), entry("result", "message", "toolResult")];
		const result = await beforeCompact(ext, branch, "old");
		assert.equal(result.compaction.firstKeptEntryId, "old");
	});

	test("keeps the default cut when the next entry is a tool result", async () => {
		const { ext } = await compactRequest();
		await ext.fire("turn_end", turnEnd);
		const branch = [entry("old"), entry("result", "message", "toolResult"), entry("sibling", "message", "toolResult")];
		const result = await beforeCompact(ext, branch, "old");
		assert.equal(result.compaction.firstKeptEntryId, "old");
	});

	test("keeps the default cut when it is later than the entry after the result", async () => {
		const { ext } = await compactRequest();
		await ext.fire("turn_end", turnEnd);
		const branch = [entry("old"), entry("result", "message", "toolResult"), entry("late"), entry("later")];
		const result = await beforeCompact(ext, branch, "later");
		assert.equal(result.compaction.firstKeptEntryId, "later");
	});
});
