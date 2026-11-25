import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, beforeEach, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const AGENT_DIR = "/agent";
const towerUrl = (file: string) => pathToFileURL(join(AGENT_DIR, "npm", "node_modules", "tower-do", file)).href;
const sources: Record<string, string> = {
	[towerUrl("state.ts")]: "export const MAX_TOWER_DO_OPEN_TASKS = 50; export const formatTakeoverWindow = () => '6h'; export const TASK_KEY_PATTERN = /^[a-z0-9][a-z0-9._-]{0,39}$/;",
	[towerUrl("index.ts")]: `export default function (pi) {
		pi.on("session_start", () => {});
		pi.on("context", (event) => ({ messages: [...event.messages, ...(event.remind ? [{ role: "custom", customType: "pi-tower-do-reminder", content: event.remind }] : [])] }));
		pi.registerTool({ name: "tower_do", description: "long", promptGuidelines: ["long"], parameters: { type: "object", description: "x", properties: { description: { type: "string", description: "long" }, key: { type: "string", pattern: "^a" } } }, execute: () => "do" });
		pi.registerTool({ name: "tower_do_status", description: "long", promptGuidelines: ["long"], parameters: { type: "object" }, execute: () => "status" });
		pi.registerTool({ name: "other", description: "kept", parameters: { description: "kept" }, execute: () => "other" });
	}`,
};
const hooks = registerHooks({
	resolve: (specifier, context, next) => (specifier in sources ? { url: specifier, format: "module", shortCircuit: true } : next(specifier, context)),
	load: (url, context, next) => (url in sources ? { format: "module", source: sources[url], shortCircuit: true } : next(url, context)),
});
after(() => hooks.deregister());

const ext = await loadExtension("tower-do-slim", { agentDir: AGENT_DIR });

describe("tower-do-slim", () => {
	useEnv({ PI_CONTEXT_CHILD: undefined, PI_SUBAGENT_CHILD: undefined });
	beforeEach(() => ext.fire("session_start", {}));
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
		assert.equal(await ext.callTool("tower_do"), "do");
		assert.equal(ext.tools.other.description, "kept");
		assert.deepEqual(ext.tools.other.parameters, { description: "kept" });
		assert.equal(ext.handlers.session_start.length, 2);
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
	const a = "- [blocked] a: long subject a @main (me)";
	const b = "- [pending] b: long subject b";

	test("moves the board reminder from the context to the next tool result, with full lines only for changed tasks", async () => {
		const first = await remind([], board(1, [a, b]));
		assert.equal(first, [header(1, 2), "Changed since the last board note:", a, b, "Open tasks: a, b"].join("\n"));
		const c = "- [in_progress] c: subject c";
		const second = await remind([toolResult("out", first!)], board(2, [a, c, "… and 1 more open task(s): d"]));
		assert.equal(second, [header(2, 3), "Changed since the last board note:", c, "New: d", "Completed or removed: b"].join("\n"));
		assert.equal(await remind([toolResult("out", first!), toolResult("out", second!)], board(3, [a, c, "… and 2 more open task(s): d, e"])), [header(3, 3), "New: e"].join("\n"));
		assert.equal(await ext.fire("tool_result", { content: [] }), undefined);
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
		test(`a fork marked by ${marker} gets no board note`, async () => {
			process.env[marker] = "1";
			assert.equal(await remind([], board(1, [a])), undefined);
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
