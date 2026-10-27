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
		pi.registerTool({ name: "tower_do", description: "long", promptGuidelines: ["long"], parameters: { type: "object", description: "x", properties: { description: { type: "string", description: "long" }, key: { type: "string", pattern: "^a" } } }, execute: () => "do" });
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
});
