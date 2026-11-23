import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

const AGENT_DIR = "/agent";
const towerUrl = (file: string) => pathToFileURL(join(AGENT_DIR, "npm", "node_modules", "tower-do", file)).href;
const sources: Record<string, string> = {
	[towerUrl("state.ts")]: "export const MAX_TOWER_DO_OPEN_TASKS = 50; export const formatTakeoverWindow = () => '6h';",
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
		assert.equal(ext.handlers.session_start.length, 1);
	});

	test("moves the board reminder from the context to the next tool result, with full lines only for changed tasks", async () => {
		const board = (revision: number, tasks: string[]) =>
			[`TowerDo shared board — you are main (revision ${revision}; 3 task(s), ${tasks.length} open, 1 completed hidden, 1 blocked, 0 unread message(s) for you).`, ...tasks, "Before your final response, reconcile."].join("\n");
		const remind = async (text: string) => {
			const user = { role: "user", content: "hi" };
			assert.deepEqual((await ext.fire("context", { messages: [user], remind: text })).messages, [user]);
			const out = await ext.fire("tool_result", { content: [{ type: "text", text: "out" }], structuredContent: { ok: 1 } });
			assert.deepEqual(out.structuredContent, { ok: 1 });
			assert.deepEqual(out.content[0], { type: "text", text: "out" });
			return out.content[1].text;
		};
		const a = "- [blocked] a: long subject a @main (me)";
		assert.equal(await remind(board(1, [a, "- [pending] b: long subject b"])), ["[board] revision 1, you are main: 2 open (1 blocked), 0 unread. tower_do_status for details.", "Changed since the last board note:", a, "- [pending] b: long subject b"].join("\n"));
		assert.equal(await remind(board(2, [a, "- [in_progress] c: subject c", "… and 1 more open task(s): d"])), ["[board] revision 2, you are main: 3 open (1 blocked), 0 unread. tower_do_status for details.", "Changed since the last board note:", "- [in_progress] c: subject c", "Other open: a, d", "Completed or removed: b"].join("\n"));
		assert.equal(await ext.fire("tool_result", { content: [] }), undefined);
	});

	test("drops a board reminder no tool result took before the turn ends", async () => {
		await ext.fire("context", { messages: [{ role: "user", content: "hi" }], remind: "board reminder" });
		await ext.fire("turn_end");
		assert.equal(await ext.fire("tool_result", { content: [] }), undefined);
	});
});
