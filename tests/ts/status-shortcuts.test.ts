import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

const AGENT_DIR = "/agent";
const towerUrl = (file: string) => pathToFileURL(join(AGENT_DIR, "npm", "node_modules", "tower-do", file)).href;
const board = { tasks: [] as Record<string, string>[], broken: false };
(globalThis as any).fakeBoard = board;
const sources: Record<string, string> = {
	[towerUrl("paths.ts")]: "export const boardFileFor = (cwd) => `board-of:${cwd}`;",
	[towerUrl("board.ts")]: `export class TowerBoard {
		async fold() { if (globalThis.fakeBoard.broken) throw new Error("no board"); return { tasks: globalThis.fakeBoard.tasks }; }
	}`,
};
const hooks = registerHooks({
	resolve: (specifier, context, next) => (specifier in sources ? { url: specifier, format: "module", shortCircuit: true } : next(specifier, context)),
	load: (url, context, next) => (url in sources ? { format: "module", source: sources[url], shortCircuit: true } : next(url, context)),
});
after(() => hooks.deregister());

const GIT = "## main...origin/main [ahead 2, behind 1]\n M a.ts\n?? b.ts\n";

async function load({ git = { stdout: GIT, code: 0 }, tasks = [] as Record<string, string>[], broken = false, asks = [] as string[] } = {}) {
	board.tasks = tasks;
	board.broken = broken;
	const ext = await loadExtension("status-shortcuts", { agentDir: AGENT_DIR, pi: { exec: async () => ({ stderr: "", killed: false, truncated: false, ...git }) } });
	const entries = asks.map((text, index) => ({ type: "custom", customType: "pending-asks", data: { action: "add", id: `a${index + 1}`, text } }));
	const ctx = ext.makeCtx({ sessionManager: { getBranch: () => entries } as any });
	return { ext, ctx, shown: () => ctx.notices.at(-1)![0] };
}

const TASKS = [
	{ key: "s1", subject: "first", status: "in_progress", owner: "me" },
	{ key: "s2", subject: "second", status: "blocked", owner: "you" },
	{ key: "s3", subject: "third", status: "completed", owner: "me" },
];

describe("status shortcuts", () => {
	test("/status shows git, board and asks without a model call", async () => {
		const { ext, ctx, shown } = await load({ tasks: TASKS, asks: ["ok to push?"] });
		await ext.runCommand("status", "", ctx);
		assert.match(shown(), /main.*ahead 2.*behind 1.*2 dirty/s);
		assert.match(shown(), /1 in progress.*1 blocked/s);
		assert.match(shown(), /1 pending ask/);
		assert.deepEqual(ext.pi.sent, []);
	});

	test("/board lists the in-progress and blocked tasks", async () => {
		const { ext, ctx, shown } = await load({ tasks: TASKS });
		await ext.runCommand("board", "", ctx);
		assert.match(shown(), /in_progress.*s1.*first.*me/);
		assert.match(shown(), /blocked.*s2.*second.*you/);
		assert.doesNotMatch(shown(), /s3/);
	});

	test("the bare word status or board is answered without starting a turn", async () => {
		const { ext, ctx, shown } = await load({ tasks: TASKS, asks: ["ok to push?"] });
		assert.deepEqual(await ext.fire("input", { text: "Status?", source: "interactive" }, ctx), { action: "handled" });
		assert.match(shown(), /git: main/);
		assert.deepEqual(await ext.fire("input", { text: "board", source: "interactive" }, ctx), { action: "handled" });
		assert.match(shown(), /s1/);
		assert.deepEqual(await ext.fire("input", { text: "asks", source: "interactive" }, ctx), { action: "handled" });
		assert.match(shown(), /a1: ok to push\?/);
		assert.deepEqual(ext.pi.sent, []);
	});
});
