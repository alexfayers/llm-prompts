import assert from "node:assert/strict";
import { basename, join } from "node:path";
import { after, describe, test } from "node:test";
import { loadExtension, restoreMocks, useEnv, useMemoryFs } from "./helpers.ts";

const forkFrom = (source: string, target: string) => ({ getSessionFile: () => join(target, `fork-of-${basename(source)}`) });

const memory = useMemoryFs();
const root = memory.root;

async function load(state = "{}") {
	memory.writeMailboxState(join(root, "agent"), "w1", state);
	memory.write(join(root, "s.jsonl"), "{}");
	return loadExtension("cd", {
		agentDir: join(root, "agent"),
		mocks: { "@earendil-works/pi-coding-agent": { SessionManager: { forkFrom } } },
		ctx: { cwd: root, sessionManager: { getSessionId: () => "owner", getSessionFile: () => join(root, "s.jsonl"), usesDefaultSessionDir: () => true } },
	});
}

useEnv({ PI_HERDSMAN_MAILBOX: "" });
after(restoreMocks);

describe("/cd refuses to move", () => {
	for (const [label, mailbox, state, refusal] of [
		["inside a managed agent", "m", "{}", "managed agent cannot"],
		["while owning agents", "", '{"ownerSessionId":"owner","agentLabel":"w1"}', "agents: w1"],
	]) {
		test(label, async () => {
			process.env.PI_HERDSMAN_MAILBOX = mailbox;
			const ext = await load(state);
			await ext.runCommand("cd", "/");
			assert.deepEqual(ext.ctx.switched, []);
			assert.match(ext.ctx.notices[0][0], new RegExp(refusal));
		});
	}
});

test("change_dir moves after the turn and continues", async () => {
	const ext = await load();
	await ext.callTool("change_dir", { path: "/" });
	await ext.fire("agent_settled", { aborted: false });
	await ext.runCommand("cd", "/");
	assert.deepEqual(ext.pi.sent, [["/cd /", { expandPromptTemplates: true }]]);
	assert.deepEqual(ext.ctx.switched, [join("/", "fork-of-s.jsonl")]);
	assert.deepEqual(ext.ctx.continued, [["Directory changed. Continue the task."]]);
});
