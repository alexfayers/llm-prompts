import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const work = fs.realpathSync(fs.mkdtempSync(join(os.tmpdir(), "usage-ledger-")));
const ledgerFile = join(work, "usage-ledger.jsonl");
const ext = await loadExtension("usage-ledger", { agentDir: work });
after(() => fs.rmSync(work, { recursive: true }));
useEnv({ PI_HERDSMAN_AGENT_DEFINITION: undefined, PI_CONTEXT_ROLE: undefined });

const eventually = async (done: () => boolean) => {
	for (let attempt = 0; attempt < 200 && !done(); attempt++) await new Promise((resolve) => setTimeout(resolve, 10));
};
const lines = () => (fs.existsSync(ledgerFile) ? fs.readFileSync(ledgerFile, "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line)) : []);
const fireAndWait = async (input: Record<string, unknown>) => {
	const before = lines().length;
	await ext.fire("tool_call", input);
	await eventually(() => lines().length > before);
};

test("a tool call appends one record naming the session, role and tool, and flags nested calls and skill reads", async () => {
	await fireAndWait({ toolName: "bash", toolCallId: "a", input: { command: "ls" } });
	await fireAndWait({ toolName: "read", toolCallId: "b", input: { path: "/x/skills/tdd/SKILL.md" } });
	await fireAndWait({ toolName: "bash", toolCallId: "p/1", parentToolCallId: "p", input: {} });
	process.env.PI_HERDSMAN_AGENT_DEFINITION = "worker";
	await fireAndWait({ toolName: "read", toolCallId: "c", input: { path: "/x/y.ts" } });

	process.env.PI_CONTEXT_ROLE = "reader";
	await fireAndWait({ toolName: "read", toolCallId: "d", input: { path: "/x/y.ts" } });
	delete process.env.PI_HERDSMAN_AGENT_DEFINITION;
	await fireAndWait({ toolName: "read", toolCallId: "e", input: { path: "/x/y.ts" } });

	const [bash, skill, nested, worker, herdsmanWins, fork] = lines();
	assert.deepEqual({ ...bash, ts: undefined }, { ts: undefined, session: "session-id", role: "main", tool: "bash", nested: false });
	assert.equal(typeof bash.ts, "number");
	assert.equal(skill.skillPath, "/x/skills/tdd/SKILL.md");
	assert.equal(nested.nested, true);
	assert.deepEqual([worker.role, worker.skillPath], ["worker", undefined]);
	assert.deepEqual([herdsmanWins.role, fork.role], ["worker", "reader"]);
});

test("an unwritable ledger does not break the tool call and warns once", async () => {
	const blocked = await loadExtension("usage-ledger", { agentDir: join(work, "no", "such", "dir") });
	assert.equal(await blocked.fire("tool_call", { toolName: "bash", toolCallId: "a", input: {} }), undefined);
	await eventually(() => blocked.ctx.notices.length > 0);
	await blocked.fire("tool_call", { toolName: "bash", toolCallId: "b", input: {} });
	await new Promise((resolve) => setTimeout(resolve, 50));
	assert.equal(blocked.ctx.notices.length, 1);
	assert.equal(blocked.ctx.notices[0][1], "warning");
});
