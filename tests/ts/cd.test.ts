import assert from "node:assert/strict";
import { basename, join } from "node:path";
import { after, describe, test } from "node:test";
import { loadExtension, restoreMocks, useMemoryFs } from "./helpers.ts";

const forkFrom = (source: string, target: string) => ({ getSessionFile: () => join(target, `fork-of-${basename(source)}`) });

const memory = useMemoryFs();
const root = memory.root;

async function load() {
	memory.write(join(root, "s.jsonl"), "{}");
	return loadExtension("cd", {
		agentDir: join(root, "agent"),
		mocks: { "@earendil-works/pi-coding-agent": { SessionManager: { forkFrom } } },
		ctx: { cwd: root, sessionManager: { getSessionFile: () => join(root, "s.jsonl"), usesDefaultSessionDir: () => true } },
	});
}

after(restoreMocks);

test("change_dir moves after the turn and continues", async () => {
	const ext = await load();
	await ext.callTool("change_dir", { path: "/" });
	await ext.fire("agent_settled", { aborted: false });
	await ext.runCommand("cd", "/");
	assert.deepEqual(ext.pi.sent, [["/cd /", { expandPromptTemplates: true }]]);
	assert.deepEqual(ext.ctx.switched, [join("/", "fork-of-s.jsonl")]);
	assert.deepEqual(ext.ctx.continued, [["Directory changed. Continue the task."]]);
});
