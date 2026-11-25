import assert from "node:assert/strict";
import { appendFileSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, afterEach, describe, mock, test } from "node:test";
import { loadExtension } from "./helpers.ts";

const AGENT_DIR = "/agent";
const towerUrl = (file: string) => pathToFileURL(join(AGENT_DIR, "npm", "node_modules", "tower-do", file)).href;
const board = { tasks: [] as { status: string; owner: string }[], file: "missing/board.jsonl", folds: 0 };
(globalThis as any).fakeBoard = board;
const sources: Record<string, string> = {
	[towerUrl("paths.ts")]: `export const boardFileFor = () => globalThis.fakeBoard.file;
	export class BoardCache {
		entryFor() { return { config: {} }; }
	}`,
	[towerUrl("board.ts")]: `export class TowerBoard {
		async fold() { globalThis.fakeBoard.folds++; return { tasks: globalThis.fakeBoard.tasks }; }
	}`,
};
const hooks = registerHooks({
	resolve: (specifier, context, next) => (specifier in sources ? { url: specifier, format: "module", shortCircuit: true } : next(specifier, context)),
	load: (url, context, next) => (url in sources ? { format: "module", source: sources[url], shortCircuit: true } : next(url, context)),
});
after(() => hooks.deregister());
const REGISTRY = Symbol.for("pi-context.registry");
afterEach(() => {
	delete (globalThis as any)[REGISTRY];
	mock.timers.reset();
	board.tasks = [];
	board.file = "missing/board.jsonl";
	board.folds = 0;
});

const HOUR = 60 * 60 * 1000;

async function decide(statuses: string[], { idleHours = 0, owner = "session-id" } = {}) {
	mock.timers.enable({ apis: ["Date"], now: 0 });
	board.tasks = statuses.map((status) => ({ status, owner }));
	const ext = await loadExtension("cache-warming", { agentDir: AGENT_DIR });
	const ctx = ext.makeCtx();
	await ext.fire("session_start", {}, ctx);
	mock.timers.setTime(idleHours * HOUR);
	return ext.fire("cache_warming_decision", { action: "stop" }, ctx);
}

describe("cache warming", () => {
	test("warms while a task is in progress", async () => {
		assert.deepEqual(await decide(["completed", "in_progress"]), { action: "warm" });
	});

	test("stops when no task of this session is in progress", async () => {
		assert.deepEqual(await decide(["completed", "in_progress"], { owner: "other-session" }), { action: "stop" });
	});

	test("stops 2 hours after the last request even with a task in progress", async () => {
		assert.deepEqual(await decide(["in_progress"], { idleHours: 2 }), { action: "stop" });
	});

	test("warms while a fork run is live, but not 2 hours after the last request", async () => {
		(globalThis as any)[REGISTRY] = { live: () => [{ name: "scan", state: "running" }] };
		assert.deepEqual(await decide(["completed"]), { action: "warm" });
		mock.timers.reset();
		assert.deepEqual(await decide(["completed"], { idleHours: 2 }), { action: "stop" });
	});

	test("folds the board file again only after the file changes", async () => {
		const dir = mkdtempSync(join(tmpdir(), "board-"));
		try {
			board.file = join(dir, "board.jsonl");
			writeFileSync(board.file, "a\n");
			const decide = async () => {
				const ext = await loadExtension("cache-warming", { agentDir: AGENT_DIR });
				return ext.fire("cache_warming_decision", { action: "stop" }, ext.makeCtx());
			};
			await decide();
			await decide();
			assert.equal(board.folds, 1);
			appendFileSync(board.file, "b\n");
			await decide();
			assert.equal(board.folds, 2);
		} finally {
			rmSync(dir, { recursive: true });
		}
	});
});
