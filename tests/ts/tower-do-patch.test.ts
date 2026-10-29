import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

type Outcome = { isError: boolean; result: { content: { type: string; text: string }[] } };
const outcome = (text: string, isError = false): Outcome => ({ isError, result: { content: [{ type: "text", text }] } });
const OK = outcome("ok");
const stale = (revision: number) =>
	outcome(`stale tower-do revision: expected 1, current board revision is ${revision}`, true);
const board = (revision: number) => ({ revision, keys: ["a", "b"] });
const BOARD = board(7);

const AGENT_DIR = "/agent";
const boardUrl = pathToFileURL(join(AGENT_DIR, "npm", "node_modules", "tower-do", "board.ts")).href;
const boardSource = 'export class TowerBoard { async fold() { return { revision: 7, tasks: [{ key: "a" }, { key: "b" }] }; } }';
const boardHooks = registerHooks({
	resolve: (specifier, context, next) => (specifier === boardUrl ? { url: boardUrl, format: "module", shortCircuit: true } : next(specifier, context)),
	load: (url, context, next) => (url === boardUrl ? { format: "module", source: boardSource, shortCircuit: true } : next(url, context)),
});
after(() => boardHooks.deregister());

const ext = await loadExtension("tower-do-patch");
const { mergeTasks, applyPatch } = ext.module;

/** Fake patch dependencies: readBoard answers the boards in turn (the last repeats), write records its arguments and answers the outcomes in turn. */
function fakeDeps(boards: unknown[], outcomes: Outcome[]) {
	const writes: any[] = [];
	let reads = 0;
	return {
		writes,
		reads: () => reads,
		readBoard: async () => boards[Math.min(reads++, boards.length - 1)],
		write: async (args: unknown) => {
			writes.push(structuredClone(args));
			return outcomes[Math.min(writes.length - 1, outcomes.length - 1)];
		},
	};
}

describe("mergeTasks", () => {
	test("upserts lead and every other current key is sent bare", () => {
		assert.deepEqual(
			mergeTasks(["a", "b", "c", "e"], [{ key: "b", status: "completed" }, { key: "d", subject: "new" }], ["e"]),
			[{ key: "b", status: "completed" }, { key: "d", subject: "new" }, { key: "a" }, { key: "c" }],
		);
	});

	for (const [label, upserts, removes, message] of [
		["a key in both tasks and remove", [{ key: "a" }], ["a"], "both"],
		["a duplicate upsert", [{ key: "b" }, { key: "b" }], [], "duplicate"],
		["an unknown remove", [], ["z"], "unknown"],
		["an empty patch", [], [], "nothing"],
	] as const) {
		test(`rejects ${label}`, () => {
			assert.throws(() => mergeTasks(["a"], upserts, removes), new RegExp(message));
		});
	}
});

describe("applyPatch", () => {
	test("sends a given revision as is and returns a stale error without retry", async () => {
		const deps = fakeDeps([BOARD], [stale(7), OK]);
		const result = await applyPatch({ remove: ["a"], baseRevision: 3 }, deps);
		assert.deepEqual(deps.writes.map((write) => write.baseRevision), [3]);
		assert.deepEqual(result, stale(7));
	});

	test("refolds and retries a stale error without a given revision", async () => {
		const boards = [7, 8, 9, 10].map(board);
		const deps = fakeDeps(boards, [stale(8), stale(9), OK]);
		assert.deepEqual(await applyPatch({ remove: ["a"] }, deps), OK);
		assert.deepEqual(deps.writes.map((write) => write.baseRevision), [7, 8, 9]);
	});

	test("gives up after three retries", async () => {
		const deps = fakeDeps([7, 8, 9, 10].map(board), [stale(8)]);
		assert.deepEqual(await applyPatch({ remove: ["a"] }, deps), stale(8));
		assert.equal(deps.writes.length, 4);
	});
});

describe("tower_do_patch tool", () => {
	const loadTool = () => loadExtension("tower-do-patch", { agentDir: AGENT_DIR });

	function ctxWith(outcomes: Outcome[]) {
		const calls: [string, any][] = [];
		const executeTool = async (tool: string, args: unknown) => {
			calls.push([tool, structuredClone(args)]);
			if (tool === "tower_do_status") return { isError: false, result: { content: [], details: { board: "/boards/board.jsonl" } } };
			return outcomes[Math.min(calls.filter(([name]) => name === "tower_do").length - 1, outcomes.length - 1)];
		};
		return { calls, ctx: { executeTool } as any };
	}

	test("folds the board and calls tower_do with the merged list", async () => {
		const { callTool } = await loadTool();
		const { calls, ctx } = ctxWith([OK]);
		const result = await callTool("tower_do_patch", { tasks: [{ key: "c", subject: "new" }], as: "me" }, ctx);
		assert.deepEqual(calls, [
			["tower_do_status", { view: "mine" }],
			["tower_do", { tasks: [{ key: "c", subject: "new" }, { key: "a" }, { key: "b" }], remove: [], baseRevision: 7, as: "me" }],
		]);
		assert.deepEqual(result.content, OK.result.content);
	});

	test("passes remove keys to tower_do", async () => {
		const { callTool } = await loadTool();
		const { calls, ctx } = ctxWith([OK]);
		await callTool("tower_do_patch", { remove: ["a"] }, ctx);
		assert.deepEqual(calls[1], ["tower_do", { tasks: [{ key: "b" }], remove: ["a"], baseRevision: 7, as: undefined }]);
	});

	test("fails the tool with the message of a failed tower_do call", async () => {
		const { callTool } = await loadTool();
		await assert.rejects(
			callTool("tower_do_patch", { remove: ["a"], baseRevision: 3 }, ctxWith([stale(7)]).ctx),
			/stale tower-do revision/,
		);
	});
});
