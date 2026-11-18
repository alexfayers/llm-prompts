import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { after, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const dir = mkdtempSync(join(tmpdir(), "load-when-"));
const project = join(dir, "project");
const conditions = { "paths:**/*.toml": ["a.md"], "env:LOAD_WHEN_SET": ["b.md"], "tool:load_when_tool": ["c.md"], "paths:docs/**": ["d.md"], "env:LOAD_WHEN_UNSET": ["e.md"], "x:y": ["f.md"], "tool:load-when-cmd": ["g.md"], "audience:main": ["b.md"] };
mkdirSync(join(dir, "rules"), { recursive: true });
mkdirSync(join(dir, "bin"));
writeFileSync(join(dir, "bin", "load-when-cmd"), "");
chmodSync(join(dir, "bin", "load-when-cmd"), 0o755);
mkdirSync(project);
writeFileSync(join(dir, "conditional-rules.json"), JSON.stringify(conditions));
for (const name of "abcdefg") writeFileSync(join(dir, "rules", `${name}.md`), name.toUpperCase());
useEnv(() => ({ LOAD_WHEN_SET: "1", LOAD_WHEN_UNSET: undefined, PI_CONTEXT_CHILD: undefined, PATH: `${join(dir, "bin")}${delimiter}${process.env.PATH}` }));
after(() => rmSync(dir, { recursive: true }));

async function start(rules = "AGENTS.md") {
	const sent: string[] = [];
	const ext = await loadExtension("load-when", { agentDir: dir, pi: { allTools: [{ name: "load_when_tool" }], sendMessage: (message: { content: string }) => sent.push(message.content) } });
	const fire = async (cwd = project, event = "before_agent_start") => {
		const contextFiles = [{ path: join(dir, rules), content: "RULES" }];
		await ext.fire(event, { systemPromptOptions: { cwd, contextFiles } });
		return contextFiles.slice(1).map((file) => file.content);
	};
	const call = async (toolName: string, input: object, text = "") => {
		await ext.fire("tool_result", { toolName, input, content: [{ type: "text", text }] }, ext.makeCtx({ cwd: project }));
		return sent.splice(0);
	};
	return { fire, call, ext };
}

test("env and tool rules load when their condition holds, and main-only rules stay out of delegates", async () => {
	assert.deepEqual(await (await start()).fire(), ["B", "C", "G"]);
	writeFileSync(join(dir, "handshake.json"), JSON.stringify({ role: "reader" }));
	process.env.PI_CONTEXT_CHILD = join(dir, "handshake.json");
	assert.deepEqual(await (await start()).fire(), ["C", "G"]);
	writeFileSync(join(dir, "handshake.json"), JSON.stringify({ role: "reader", inherited: true }));
	assert.deepEqual(await (await start()).fire(), ["B", "C", "G"]);
});

test("nothing loads without the agent dir's AGENTS.md", async () => {
	const { fire, call } = await start("other.md");
	assert.deepEqual(await fire(), []);
	assert.deepEqual(await call("read", { path: "pyproject.toml" }), []);
});

test("env conditions are checked again only on a new session or cwd, and pi tools on every prompt", async () => {
	const { fire, ext } = await start();
	await fire();
	ext.pi.allTools = [];
	assert.deepEqual(await fire(), ["B", "G"]);
	ext.pi.allTools = [{ name: "load_when_tool" }];
	process.env.LOAD_WHEN_UNSET = "1";
	assert.deepEqual(await fire(), ["B", "C", "G"]);
	assert.deepEqual(await fire(dir), ["B", "C", "E", "G"]);
	delete process.env.LOAD_WHEN_UNSET;
	await ext.fire("session_start", {});
	assert.deepEqual(await fire(dir), ["B", "C", "G"]);
});

test("a paths rule is sent once a read, grep, find, edit or write call touches a matching file", async () => {
	const { fire, call, ext } = await start();
	await fire();
	assert.deepEqual(await call("read", { path: "src/main.py" }), []);
	assert.deepEqual(await call("bash", { command: "cat pyproject.toml" }), []);
	assert.deepEqual(await call("read", { path: join(project, "pyproject.toml") }), ["A"]);
	assert.deepEqual(await call("find", { pattern: "*.toml" }, "pyproject.toml"), []);
	assert.deepEqual(await call("write", { path: "docs/new.md" }), ["D"]);
	await ext.fire("session_compact", {});
	assert.deepEqual(await call("find", { pattern: "*.toml" }, "sub/pyproject.toml"), ["A"]);
	await ext.fire("session_start", {});
	await fire();
	assert.deepEqual(await call("grep", { pattern: "x", path: "docs" }, "guide.md:3: x"), ["D"]);
	await ext.fire("session_start", {});
	await fire();
	assert.deepEqual(await call("edit", { path: "Cargo.toml" }), ["A"]);
});

test("a resumed session does not send a paths rule its branch already holds", async () => {
	const { fire, call, ext } = await start();
	const branch = [{ id: "1", type: "custom_message", customType: "load-when", details: { rule: "a.md" } }];
	await ext.fire("session_start", { reason: "resume" }, ext.makeCtx({ sessionManager: { getBranch: () => branch } }));
	await fire();
	assert.deepEqual(await call("read", { path: "pyproject.toml" }), []);
});
