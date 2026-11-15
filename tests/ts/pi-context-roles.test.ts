import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";
import { ROLES, decide, rewriteForWorktree } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/roles.ts";

describe("decide", () => {
	test("a reader reads but may not edit, write or fork", () => {
		assert.equal(decide(ROLES.reader, "read", { path: "a.ts" }), undefined);
		assert.equal(decide(ROLES.reader, "codemode", { code: "1" }), undefined);
		assert.deepEqual(decide(ROLES.reader, "edit", { path: "a.ts" }), { block: true, reason: "role reader may not use edit" });
		assert.match(decide(ROLES.reader, "fork", {})?.reason ?? "", /may not use fork/);
	});

	test("MCP tools follow the role's allowlist, including nested calls", () => {
		assert.equal(decide(ROLES.reader, "mcp__memory__search_nodes", {}), undefined);
		assert.match(decide(ROLES.writer, "mcp__memory__create_entities", {})?.reason ?? "", /may not use mcp__memory__create_entities/);
		assert.match(decide(ROLES.reader, "tower_do", {})?.reason ?? "", /may not use tower_do/);
	});

	test("a writer may edit and write only inside its worktree", () => {
		const wt = "/wt/a";
		assert.equal(decide(ROLES.writer, "edit", { path: "/wt/a/src/x.ts" }, wt), undefined);
		assert.equal(decide(ROLES.writer, "write", { file_path: "/wt/a" }, wt), undefined);
		assert.match(decide(ROLES.writer, "write", { path: "/main/x.ts" }, wt)?.reason ?? "", /only inside \/wt\/a/);
		assert.match(decide(ROLES.writer, "edit", { path: "/wt/a/../b/x.ts" }, wt)?.reason ?? "", /only inside/);
		assert.match(decide(ROLES.writer, "edit", { path: "/wt/ab/x.ts" }, wt)?.reason ?? "", /only inside/);
	});

	test("a writer may not reach outside its worktree through ~", () => {
		for (const target of ["~/x.ts", "~", "~/../x.ts"]) {
			assert.match(decide(ROLES.writer, "edit", { path: target }, "/wt/a")?.reason ?? "", /only inside/);
		}
		assert.equal(decide(ROLES.writer, "edit", { path: "~/wt/x.ts" }, path.join(os.homedir(), "wt")), undefined);
	});
});

describe("rewriteForWorktree", () => {
	const wt = "/wt/a";
	const main = "/main";
	const rewrite = (toolName: string, input: Record<string, unknown>) => (rewriteForWorktree(toolName, input, wt, main), input);

	test("bash runs in the worktree and main paths in the command point at it", () => {
		assert.equal(rewrite("bash", { command: "cat /main/src/x.ts && ls /mainly /main" }).command, "cd '/wt/a' && cat /wt/a/src/x.ts && ls /mainly /wt/a");
		const again = rewrite("bash", { command: "cd '/wt/a' && ls" });
		assert.equal(again.command, "cd '/wt/a' && ls");
	});

	test("file paths move to the worktree and relative ones resolve against it", () => {
		assert.equal(rewrite("edit", { path: "/main/src/x.ts" }).path, "/wt/a/src/x.ts");
		assert.equal(rewrite("read", { file_path: "src/x.ts" }).file_path, "/wt/a/src/x.ts");
		assert.equal(rewrite("grep", { cwd: "/main" }).cwd, "/wt/a");
		assert.equal(rewrite("write", { path: "/elsewhere/x" }).path, "/elsewhere/x");
		assert.equal(decide(ROLES.writer, "write", rewrite("write", { path: "/main/x" }), wt), undefined);
	});

	test("~ paths resolve against the home directory before they are remapped", () => {
		const home = path.join(os.homedir(), "proj");
		const input = { path: "~/proj/src/x.ts" };
		rewriteForWorktree("edit", input, wt, home);
		assert.equal(input.path, "/wt/a/src/x.ts");
		const outside = { path: "~/other.ts" };
		rewriteForWorktree("write", outside, wt, home);
		assert.equal(outside.path, path.join(os.homedir(), "other.ts"));
		assert.match(decide(ROLES.writer, "write", outside, wt)?.reason ?? "", /only inside/);
	});

	test("a worktree under the main directory is not remapped twice", () => {
		const input = { command: "ls /main/.wt/a/x /main/y" };
		rewriteForWorktree("bash", input, "/main/.wt/a", main);
		assert.equal(input.command, "cd '/main/.wt/a' && ls /main/.wt/a/x /main/.wt/a/y");
	});
});

describe("child mode", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-roles-"));
	after(() => fs.rmSync(dir, { recursive: true }));
	const handshake = (data: unknown) => {
		const file = path.join(dir, `h${fs.readdirSync(dir).length}.json`);
		fs.writeFileSync(file, typeof data === "string" ? data : JSON.stringify(data));
		return file;
	};
	const call = async (file: string | undefined, toolName: string, input: Record<string, unknown>) => {
		if (file) process.env.PI_CONTEXT_CHILD = file;
		const ext = await loadExtension("pi-context/index", { ctx: { cwd: "/main" } });
		return { ext, result: (await ext.fire("tool_call", { toolName, input })) as unknown };
	};
	useEnv({ PI_CONTEXT_CHILD: undefined });

	test("without PI_CONTEXT_CHILD no call is guarded", async () => {
		const { ext } = await call(undefined, "edit", {});
		assert.equal(ext.handlers.tool_call, undefined);
	});

	test("a writer's calls are rewritten into its worktree and blocked outside the role", async () => {
		const file = handshake({ role: "writer", worktree: "/wt/a" });
		const input = { command: "ls /main" };
		assert.equal((await call(file, "bash", input)).result, undefined);
		assert.equal(input.command, "cd '/wt/a' && ls /wt/a");
		assert.deepEqual((await call(file, "edit", { path: "/other/x" })).result, { block: true, reason: "role writer may write only inside /wt/a" });
		assert.match(String(((await call(file, "fork", {})).result as any).reason), /may not use fork/);
		assert.match(String(((await call(handshake({ role: "writer" }), "write", { path: "x" })).result as any).reason), /no worktree/);
	});

	test("a reader cannot edit and its bash command is unchanged", async () => {
		const file = handshake({ role: "reader" });
		const input = { command: "ls /main" };
		assert.equal((await call(file, "bash", input)).result, undefined);
		assert.equal(input.command, "ls /main");
		assert.match(String(((await call(file, "edit", { path: "x" })).result as any).reason), /may not use edit/);
	});

	test("a writer's process starts only in its worktree", async () => {
		const file = handshake({ role: "writer", worktree: "/wt/a" });
		const input = { action: "start", command: "ls /main", cwd: "/other" };
		assert.equal((await call(file, "process", input)).result, undefined);
		assert.deepEqual(input, { action: "start", command: "ls /wt/a", cwd: "/wt/a" });
		assert.equal((await call(file, "process", { action: "list" })).result, undefined);
		assert.match(decide(ROLES.writer, "process", { action: "start", cwd: "/other" }, "/wt/a")?.reason ?? "", /only inside/);
		assert.match(String(((await call(handshake({ role: "writer" }), "process", { action: "start", command: "ls" })).result as any).reason), /no worktree/);
	});

	test("an unreadable or unknown-role handshake blocks every call", async () => {
		for (const file of [path.join(dir, "missing.json"), handshake("{"), handshake({ role: "root" })]) {
			assert.match(String(((await call(file, "read", {})).result as any).reason), /handshake/);
		}
	});
});
