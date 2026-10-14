import assert from "node:assert/strict";
import { test } from "node:test";
import { loadExtension } from "./helpers.ts";

const ENTRY_TYPE = "hide-tools";
const HEADLESS_ONLY = ["tower_do", "tower_do_status", "tower_do_talk", "tower_do_patch", "process"];

async function startSession(tools: string[], mode: string, savedHidden?: string[]) {
	const branch = savedHidden === undefined ? [] : [{ type: "custom", customType: ENTRY_TYPE, data: { hidden: savedHidden } }];
	const ext = await loadExtension("hide-tools", { pi: { activeTools: tools }, ctx: { mode, sessionManager: { getBranch: () => branch } as any } });
	await ext.fire("session_start");
	return { tools: ext.pi.activeTools, appended: ext.pi.appended };
}

test("session start hides only the unused tools", async () => {
	const tools = ["lsp_hover", "ast_search", "lsp_diagnostics", "read", "bash"];
	assert.deepEqual((await startSession(tools, "tui")).tools, ["lsp_diagnostics", "read", "bash"]);
});

test("a new headless session also hides the interactive tools and saves them", async () => {
	const result = await startSession(["read", ...HEADLESS_ONLY, "bash"], "print");
	assert.deepEqual(result.tools, ["read", "bash"]);
	assert.deepEqual(result.appended, [[ENTRY_TYPE, { hidden: HEADLESS_ONLY }]]);
});
