import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, beforeEach, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const AGENT_DIR = "/agent";
const towerUrl = (file: string) => pathToFileURL(join(AGENT_DIR, "npm", "node_modules", "tower-do", file)).href;
const sources: Record<string, string> = {
	[towerUrl("state.ts")]: `export const MAX_TOWER_DO_OPEN_TASKS = 50; export const formatTakeoverWindow = () => '6h'; export const TASK_KEY_PATTERN = /^[a-z0-9][a-z0-9._-]{0,39}$/;
		export const normalizeIdentity = (identity) => identity; export const parseActivityLine = (line) => JSON.parse(line);`,
	[towerUrl("index.ts")]: `export default function (pi) {
		pi.on("session_start", () => {});
		pi.on("context", (event) => ({ messages: [...event.messages, ...(event.remind ? [{ role: "custom", customType: "pi-tower-do-reminder", content: event.remind }] : [])] }));
		pi.registerTool({ name: "tower_do", description: "long", promptGuidelines: ["long"], parameters: { type: "object", description: "x", properties: { description: { type: "string", description: "long" }, key: { type: "string", pattern: "^a" } } }, execute: (_id, params, _signal, _update, ctx) => globalThis.towerCall("tower_do", params, ctx) });
		pi.registerTool({ name: "tower_do_talk", description: "long", promptGuidelines: ["long"], parameters: { type: "object" }, execute: (_id, params, _signal, _update, ctx) => globalThis.towerCall("tower_do_talk", params, ctx) });
		pi.registerTool({ name: "tower_do_status", description: "long", promptGuidelines: ["long"], parameters: { type: "object" }, execute: () => "status" });
		pi.registerTool({ name: "other", description: "kept", parameters: { description: "kept" }, execute: () => "other" });
	}`,
	[towerUrl("paths.ts")]: "export const boardFileFor = (cwd) => `${cwd}/no-board-file.jsonl`; export class BoardCache { entryFor() { return { config: {} }; } }",
	[towerUrl("board.ts")]: `export class TowerBoard {
		async fold() { return { revision: 7, tasks: globalThis.boardTasks() }; }
		async rawLines() { return globalThis.boardActivity.map((entry) => JSON.stringify(entry)); }
	}`,
};
type Call = { tool: string; params: any; cwd?: string };
const globals = globalThis as unknown as { towerDoCalls: Call[]; boardTasks: () => unknown[]; boardActivity: { by: string; at: number }[]; towerCall: (tool: string, params: any, ctx: any) => string };
globals.towerDoCalls = [];
globals.boardTasks = () => [];
globals.boardActivity = [];
let rejectWrites = false;
globals.towerCall = (tool, params, ctx) => {
	globals.towerDoCalls.push({ tool, params, cwd: ctx?.cwd });
	if (rejectWrites && tool === "tower_do") throw new Error("stale baseRevision");
	return "do";
};
const hooks = registerHooks({
	resolve: (specifier, context, next) => (specifier in sources ? { url: specifier, format: "module", shortCircuit: true } : next(specifier, context)),
	load: (url, context, next) => (url in sources ? { format: "module", source: sources[url], shortCircuit: true } : next(url, context)),
});
after(() => hooks.deregister());

const ext = await loadExtension("tower-do-slim", { agentDir: AGENT_DIR });

describe("tower-do-slim", () => {
	useEnv({ PI_CONTEXT_CHILD: undefined, PI_SUBAGENT_CHILD: undefined });
	beforeEach(async () => {
		globals.boardTasks = () => [];
		globals.boardActivity = [];
		rejectWrites = false;
		await ext.fire("session_start", {});
		globals.towerDoCalls = [];
	});
	test("replaces the description and guidelines of a tower-do tool", () => {
		const { tower_do } = ext.tools;
		assert.match(tower_do.description, /idle 6h\+/);
		assert.match(tower_do.description, /At most 50 /);
		assert.ok(tower_do.promptGuidelines.every((line: string) => line !== "long"));
		assert.match(ext.tools.tower_do_status.promptGuidelines[0], /Pass taskKey to read your own task/);
	});

	test("drops parameter descriptions but keeps constraints and a property named description", () => {
		assert.deepEqual(ext.tools.tower_do.parameters, {
			type: "object",
			properties: { description: { type: "string" }, key: { type: "string", pattern: "^a" } },
		});
	});

	test("keeps the tool's execute, leaves other tools alone and passes other pi calls through", async () => {
		assert.equal(await ext.callTool("tower_do", {}), "do");
		assert.equal(ext.tools.other.description, "kept");
		assert.deepEqual(ext.tools.other.parameters, { description: "kept" });
		assert.equal(ext.handlers.session_start.length, 3);
	});

	const DAY = 24 * 60 * 60_000;
	const ago = (days: number) => Date.now() - days * DAY;
	const row = (key: string, ageDays: number, extra: Record<string, unknown> = {}) => ({ key, subject: `subject ${key}`, status: "in_progress", owner: "gone", dependsOn: [], updatedAt: ago(ageDays), ...extra });
	const start = (reason = "startup", ctx = ext.makeCtx()) => ext.fire("session_start", { reason }, ctx);
	const writes = () => globals.towerDoCalls.filter(({ tool }) => tool === "tower_do").map(({ params }) => params.remove);

	test("a startup tells each idle owner, then removes its open tasks idle for more than 3 days as tower, against the folded revision", async () => {
		const ctx = ext.makeCtx({ cwd: "/repo" });
		globals.boardTasks = () => [row("old", 4), row("fresh", 2), row("done", 9, { status: "completed" }), row("other", 5, { owner: "left" })];
		globals.boardActivity = [{ by: "gone", at: ago(4) }, { by: "left", at: ago(6) }];
		await start("startup", ctx);
		assert.deepEqual(globals.towerDoCalls.map(({ tool, params, cwd }) => [tool, params.to, cwd]), [["tower_do_talk", "gone", "/repo"], ["tower_do_talk", "left", "/repo"], ["tower_do", undefined, "/repo"]]);
		assert.match(globals.towerDoCalls[0].params.body, /^- old \[in_progress\]: subject old$/m);
		assert.deepEqual(globals.towerDoCalls[2].params, { as: "tower", baseRevision: 7, tasks: [], remove: ["old", "other"] });
		assert.deepEqual(ctx.notices.at(-1), ["tower-do: removed open tasks of owners idle for 3 days: old, other", "info"]);
	});

	test("keeps tasks of this session, of an owner active in the last 3 days, unowned, blocked or waiting on a blocker", async () => {
		globals.boardTasks = () => [row("mine", 9, { owner: "session-id" }), row("busy", 9, { owner: "alive" }), row("free", 9, { owner: undefined }), row("parked", 9, { status: "blocked" }), row("waiting", 9, { status: "pending", blockedBy: ["review"] }), row("old", 9)];
		globals.boardActivity = [{ by: "alive", at: ago(1) }];
		await start("new");
		assert.deepEqual(writes(), [["old"]]);
	});

	for (const reason of ["resume", "reload", "fork"])
		test(`a ${reason} removes no task`, async () => {
			globals.boardTasks = () => [row("old", 9)];
			await start(reason);
			assert.deepEqual(globals.towerDoCalls, []);
		});

	test("an idle task that a kept task depends on stays, with every idle task it depends on", async () => {
		globals.boardTasks = () => [row("base", 6), row("middle", 5, { dependsOn: ["base"] }), row("live", 1, { dependsOn: ["middle"] }), row("lone", 4)];
		await start();
		assert.deepEqual(writes(), [["lone"]]);
	});

	test("a board with no idle task, or one that cannot be read, gets no write, and a rejected removal tells the user nothing", async () => {
		globals.boardTasks = () => [row("fresh", 1)];
		await start();
		globals.boardTasks = () => {
			throw new Error("unreadable");
		};
		await start();
		assert.deepEqual(globals.towerDoCalls, []);
		globals.boardTasks = () => [row("old", 4)];
		rejectWrites = true;
		const ctx = ext.makeCtx();
		await start("startup", ctx);
		assert.deepEqual(writes(), [["old"]]);
		assert.deepEqual(ctx.notices, []);
	});

	const board = (revision: number, tasks: string[], identity = "main") =>
		[`TowerDo shared board — you are ${identity} (revision ${revision}; 3 task(s), ${tasks.length} open, 1 completed hidden, 1 blocked, 0 unread message(s) for you).`, ...tasks, "Before your final response, reconcile."].join("\n");
	const header = (revision: number, open: number, identity = "main") => `[board] revision ${revision}, you are ${identity}: ${open} open (1 blocked), 0 unread. tower_do_status for details.`;
	const toolResult = (...texts: string[]) => ({ role: "toolResult", content: texts.map((text) => ({ type: "text", text })) });
	/** One model call that sees `visible`, then one tool result; returns the board note the result carries, or undefined. */
	const remind = async (visible: any[], text: string, event: Record<string, unknown> = {}) => {
		const user = { role: "user", content: "hi" };
		assert.deepEqual((await ext.fire("context", { messages: [user, ...visible], remind: text })).messages, [user, ...visible]);
		const out = await ext.fire("tool_result", { content: [{ type: "text", text: "out" }], structuredContent: { ok: 1 }, ...event });
		if (!out) return undefined;
		assert.deepEqual(out.structuredContent, { ok: 1 });
		assert.deepEqual(out.content[0], { type: "text", text: "out" });
		return out.content[1].text as string;
	};
	const more = (...keys: string[]) => `\u2026 and ${keys.length} more open task(s): ${keys.join(", ")}`;
	const a = "- [blocked] a: long subject a @main (me)";
	const b = "- [pending] b: long subject b";

	test("moves the board reminder from the context to the next tool result, with full lines only for changed tasks", async () => {
		const first = await remind([], board(1, [a, b]));
		assert.equal(first, [header(1, 2), "Changed since the last board note:", a, b, "Open tasks: a, b"].join("\n"));
		const c = "- [in_progress] c: subject c";
		const second = await remind([toolResult("out", first!)], board(2, [a, c, more("d")]));
		assert.equal(second, [header(2, 3), "Changed since the last board note:", c, "New: d", "Completed or removed: b"].join("\n"));
		assert.equal(await remind([toolResult("out", first!), toolResult("out", second!)], board(3, [a, c, more("d", "e")])), [header(3, 3), "New: e"].join("\n"));
		assert.equal(await ext.fire("tool_result", { content: [] }), undefined);
	});

	test("lists only the caller's tasks and tasks updated in the last 24h, with a count of the rest", async () => {
		const hours = (n: number) => Date.now() - n * 60 * 60_000;
		const mine = "- [in_progress] mine: subject @main (me)";
		const recent = "- [pending] recent: subject @peer";
		const idle = "- [pending] idle: subject @peer";
		globals.boardTasks = () => [
			{ key: "mine", status: "in_progress", owner: "main", updatedAt: hours(40) },
			{ key: "recent", status: "pending", owner: "peer", updatedAt: hours(2) },
			{ key: "idle", status: "pending", owner: "peer", updatedAt: hours(30) },
			{ key: "old", status: "pending", updatedAt: hours(50) },
		];
		const first = (await remind([], board(1, [mine, recent, idle, more("old")])))!;
		assert.equal(first, [header(1, 4), "Changed since the last board note:", mine, recent, "Open tasks: mine, recent", "Not listed: 2 open task(s) of others idle over 24h."].join("\n"));
		assert.equal(await remind([toolResult("out", first)], board(2, [mine, recent, idle, more("old")])), header(2, 4));
		globals.boardTasks = () => [{ key: "idle", status: "in_progress", owner: "peer", updatedAt: hours(0) }, { key: "mine", status: "in_progress", owner: "main", updatedAt: hours(40) }];
		const woke = "- [in_progress] idle: subject @peer";
		assert.equal(await remind([toolResult("out", first)], board(3, [woke, mine])), [header(3, 2), "Changed since the last board note:", woke, "Completed or removed: recent"].join("\n"));
	});

	test("a result of a call another tool made takes no note, and the next top-level result does", async () => {
		const user = { role: "user", content: "hi" };
		await ext.fire("context", { messages: [user], remind: board(1, [a]) });
		assert.equal(await ext.fire("tool_result", { content: [], parentToolCallId: "call-1" }), undefined);
		assert.equal((await ext.fire("tool_result", { content: [] })).content[0].text, [header(1, 1), "Changed since the last board note:", a, "Open tasks: a"].join("\n"));
	});

	test("a change a folded note stated prints again after a later note that says nothing changed", async () => {
		const first = (await remind([], board(1, [a, b])))!;
		const c = "- [in_progress] c: subject c";
		await remind([toolResult("out", first)], board(2, [a, b, c]));
		const quiet = (await remind([toolResult("out", first)], board(3, [a, b, c])))!;
		assert.equal(quiet, [header(3, 3), "Changed since the last board note:", c].join("\n"));
		assert.equal(await remind([toolResult("out", first), toolResult("out", quiet)], board(4, [a, b, c])), header(4, 3));
	});

	test("a board of no open tasks is stated, and later tasks arrive as changes", async () => {
		const empty = (await remind([], board(1, [])))!;
		assert.equal(empty, [header(1, 0), "Open tasks:"].join("\n"));
		assert.equal(await remind([toolResult("out", empty)], board(2, [])), header(2, 0));
		assert.equal(await remind([toolResult("out", empty)], board(3, [a])), [header(3, 1), "Changed since the last board note:", a].join("\n"));
	});

	describe("text that only looks like a board note", () => {
		const full = [header(1, 1), "Changed since the last board note:", a, "Open tasks: a"].join("\n");
		const fullAgain = [header(2, 1), "Changed since the last board note:", a, "Open tasks: a"].join("\n");
		const cases: Record<string, any[]> = {
			"a note that is not the last part of its result": [toolResult(full, "out")],
			"a note of another identity": [toolResult("out", full.replaceAll("main", "other"))],
			"a note with a line outside the note format": [toolResult("out", `${full}\nsource code`)],
			"a note with a task line before the changed label": [toolResult("out", [header(1, 1), a, "Open tasks: a"].join("\n"))],
			"a note with an invalid task key": [toolResult("out", [header(1, 1), "Open tasks: A!"].join("\n"))],
			"a note in a message that is not a tool result": [{ role: "assistant", content: [{ type: "text", text: full }] }],
			"a change-only note with no full note before it": [toolResult("out", [header(1, 1), "Changed since the last board note:", a].join("\n"))],
		};
		for (const [name, visible] of Object.entries(cases))
			test(`${name} is not board state`, async () => {
				assert.equal(await remind(visible, board(2, [a])), fullAgain);
			});
	});

	for (const marker of ["PI_CONTEXT_CHILD", "PI_SUBAGENT_CHILD"])
		test(`a fork marked by ${marker} gets no board note and expires no task`, async () => {
			process.env[marker] = "1";
			assert.equal(await remind([], board(1, [a])), undefined);
			globals.boardTasks = () => [row("old", 4)];
			await start();
			assert.deepEqual(globals.towerDoCalls, []);
		});

	test("a revision already noted gets no second note, even when the note was folded away", async () => {
		await remind([], board(7, [a]));
		assert.equal(await remind([], board(7, [a])), undefined);
		assert.equal(await remind([], board(8, [a, b])), [header(8, 2), "Changed since the last board note:", a, b, "Open tasks: a, b"].join("\n"));
	});

	test("a reload or resume keeps the revision already noted", async () => {
		await remind([], board(7, [a]));
		const [customType, data] = ext.pi.appended.at(-1)!;
		const entry = { type: "custom", customType, data };
		const ctx = ext.makeCtx();
		ctx.sessionManager.getBranch = () => [entry] as never;
		await ext.fire("session_start", {}, ctx);
		assert.equal(await remind([], board(7, [a])), undefined);
		assert.equal((await remind([], board(8, [a])))?.startsWith(header(8, 1)), true);
	});

	test("drops a board reminder no tool result took before the turn ends", async () => {
		await ext.fire("context", { messages: [{ role: "user", content: "hi" }], remind: "board reminder" });
		await ext.fire("turn_end");
		assert.equal(await ext.fire("tool_result", { content: [] }), undefined);
	});
});
