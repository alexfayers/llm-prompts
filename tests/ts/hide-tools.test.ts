import assert from "node:assert/strict";
import { test } from "node:test";
import { loadExtension } from "./helpers.ts";

test("session start hides only the unused tools", async () => {
	const tools = ["lsp_hover", "ast_search", "lsp_diagnostics", "read", "bash"];
	const ext = await loadExtension("hide-tools", { pi: { activeTools: tools } });
	await ext.fire("session_start");
	assert.deepEqual(ext.pi.activeTools, ["lsp_diagnostics", "read", "bash"]);
});
