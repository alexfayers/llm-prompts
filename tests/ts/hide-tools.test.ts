import assert from "node:assert/strict";
import { test } from "node:test";
import { loadExtension } from "./helpers.ts";

const ENTRY_TYPE = "hide-tools";
const HEADLESS_ONLY = ["tower_do", "tower_do_status", "tower_do_talk", "tower_do_patch", "process"];

async function startSession(tools: string[], mode: string, savedHidden?: string[], registered: string[] = tools) {
	const branch = savedHidden === undefined ? [] : [{ type: "custom", customType: ENTRY_TYPE, data: { hidden: savedHidden } }];
	const allTools = registered.map((name) => ({ name }));
	const ext = await loadExtension("hide-tools", { pi: { activeTools: tools, allTools }, ctx: { mode, sessionManager: { getBranch: () => branch } as any } });
	await ext.fire("session_start");
	return { tools: ext.pi.activeTools, appended: ext.pi.appended };
}

test("a new headless session also hides the interactive tools and saves them", async () => {
	const result = await startSession(["read", ...HEADLESS_ONLY, "bash"], "print");
	assert.deepEqual(result.tools, ["read", "bash"]);
	assert.deepEqual(result.appended, [[ENTRY_TYPE, { hidden: HEADLESS_ONLY }]]);
});

test("session start turns back on core tools a resumed session lost", async () => {
	const handshake = process.env.PI_CONTEXT_CHILD;
	delete process.env.PI_CONTEXT_CHILD;
	try {
		const registered = ["read", "bash", "edit", "write", "codemode"];
		assert.deepEqual((await startSession(["codemode"], "tui", undefined, registered)).tools, ["codemode", "read", "bash", "edit", "write"]);
	} finally {
		if (handshake !== undefined) process.env.PI_CONTEXT_CHILD = handshake;
	}
});

test("a delegate keeps the core tools its role left off", async () => {
	const handshake = process.env.PI_CONTEXT_CHILD;
	process.env.PI_CONTEXT_CHILD = "/tmp/handshake.json";
	try {
		assert.deepEqual((await startSession(["codemode"], "tui", undefined, ["read", "codemode"])).tools, ["codemode"]);
	} finally {
		if (handshake === undefined) delete process.env.PI_CONTEXT_CHILD;
		else process.env.PI_CONTEXT_CHILD = handshake;
	}
});
