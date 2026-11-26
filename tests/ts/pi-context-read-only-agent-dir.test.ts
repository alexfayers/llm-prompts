import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { readOnlyAgentDir } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/read-only-agent-dir.ts";

test("a read-only agent directory drops the language server extension, keeps other packages and links the rest", () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-"));
	const agentDir = path.join(root, "agent");
	fs.mkdirSync(path.join(agentDir, "skills"), { recursive: true });
	fs.writeFileSync(path.join(agentDir, "settings.json"), JSON.stringify({ theme: "x", packages: ["npm:pi-lsp-extension@1.4.0", "npm:other@1.0.0", { source: "npm:pi-lsp-extension@2.0.0" }, { source: "../local-ext" }] }));
	const dest = readOnlyAgentDir(agentDir).dir;
	assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dest, "settings.json"), "utf8")), { theme: "x", packages: ["npm:other@1.0.0", { source: path.join(root, "local-ext") }] });
	assert.equal(fs.realpathSync(path.join(dest, "skills")), fs.realpathSync(path.join(agentDir, "skills")));
	fs.rmSync(root, { recursive: true });
});

test("plain relative paths keep their original base, and override and glob patterns stay as written", () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-"));
	fs.writeFileSync(path.join(root, "settings.json"), JSON.stringify({ skills: ["../s", "x/y", "/abs", "+x/y", "-x/z", "!x/*"], prompts: ["p/*.md"], themes: ["t"], extensions: ["-extensions/foo.ts", "~/e", "e.ts"] }));
	const handle = readOnlyAgentDir(root);
	const { skills, prompts, themes, extensions } = JSON.parse(fs.readFileSync(path.join(handle.dir, "settings.json"), "utf8"));
	assert.deepEqual([skills, prompts, themes, extensions], [[path.resolve(root, "../s"), `${root}/x/y`, "/abs", "+x/y", "-x/z", "!x/*"], ["p/*.md"], [`${root}/t`], ["-extensions/foo.ts", "~/e", `${root}/e.ts`]]);
	fs.rmSync(root, { recursive: true });
});

test("a failed setup removes the directory it made", () => {
	const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-root-"));
	assert.throws(() => readOnlyAgentDir(path.join(tempRoot, "missing"), tempRoot));
	assert.deepEqual(fs.readdirSync(tempRoot), []);
	fs.rmSync(tempRoot, { recursive: true });
});

test("the same agent directory and settings give the same directory, and different settings give another", () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-"));
	const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-root-"));
	fs.writeFileSync(path.join(root, "settings.json"), JSON.stringify({ theme: "x" }));
	const first = readOnlyAgentDir(root, tempRoot).dir;
	assert.equal(readOnlyAgentDir(root, tempRoot).dir, first);
	fs.writeFileSync(path.join(root, "settings.json"), JSON.stringify({ theme: "y" }));
	assert.notEqual(readOnlyAgentDir(root, tempRoot).dir, first);
	fs.rmSync(root, { recursive: true });
	fs.rmSync(tempRoot, { recursive: true });
});

test("a changed settings file or link in the shared directory is rebuilt before reuse", () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-"));
	const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-root-"));
	fs.mkdirSync(path.join(root, "skills"));
	fs.writeFileSync(path.join(root, "settings.json"), JSON.stringify({ packages: ["npm:pi-lsp-extension@1.0.0"] }));
	const { dir } = readOnlyAgentDir(root, tempRoot);
	fs.writeFileSync(path.join(dir, "settings.json"), JSON.stringify({ packages: ["npm:pi-lsp-extension@1.0.0"] }));
	fs.rmSync(path.join(dir, "skills"));
	fs.symlinkSync("/etc", path.join(dir, "skills"));
	assert.equal(readOnlyAgentDir(root, tempRoot).dir, dir);
	assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir, "settings.json"), "utf8")), { packages: [] });
	assert.equal(fs.readlinkSync(path.join(dir, "skills")), path.join(root, "skills"));
	fs.rmSync(root, { recursive: true });
	fs.rmSync(tempRoot, { recursive: true });
});

test("a symlink or an open directory where the private root belongs is refused", () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-"));
	const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-root-"));
	const { dir } = readOnlyAgentDir(root, tempRoot);
	const privateRoot = path.dirname(dir);
	fs.chmodSync(privateRoot, 0o777);
	assert.throws(() => readOnlyAgentDir(root, tempRoot), /private/);
	fs.rmSync(privateRoot, { recursive: true });
	fs.symlinkSync(root, privateRoot);
	assert.throws(() => readOnlyAgentDir(root, tempRoot), /private/);
	fs.rmSync(root, { recursive: true });
	fs.rmSync(tempRoot, { recursive: true });
});

test("a rebuild waits for another fork that holds the lock of the same directory", async () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-"));
	const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-root-"));
	const { dir } = readOnlyAgentDir(root, tempRoot);
	fs.writeFileSync(path.join(dir, "settings.json"), "stale");
	const holder = spawn(process.execPath, [
		"-e",
		'const fs = require("node:fs"); const lock = process.argv[1]; fs.mkdirSync(lock); console.log("held"); setTimeout(() => fs.rmdirSync(lock), 400);',
		`${dir}.lock`,
	]);
	await once(holder.stdout, "data");
	const started = Date.now();
	assert.equal(readOnlyAgentDir(root, tempRoot).dir, dir);
	assert.ok(Date.now() - started >= 300);
	assert.equal(fs.readFileSync(path.join(dir, "settings.json"), "utf8"), "{}");
	assert.equal(fs.existsSync(`${dir}.lock`), false);
	fs.rmSync(root, { recursive: true });
	fs.rmSync(tempRoot, { recursive: true });
});

test("a lock left behind by a stopped fork is broken once it is old", () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-"));
	const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-root-"));
	const { dir } = readOnlyAgentDir(root, tempRoot);
	fs.writeFileSync(path.join(dir, "settings.json"), "stale");
	fs.mkdirSync(`${dir}.lock`);
	const old = new Date(Date.now() - 60_000);
	fs.utimesSync(`${dir}.lock`, old, old);
	assert.equal(readOnlyAgentDir(root, tempRoot).dir, dir);
	assert.equal(fs.readFileSync(path.join(dir, "settings.json"), "utf8"), "{}");
	fs.rmSync(root, { recursive: true });
	fs.rmSync(tempRoot, { recursive: true });
});
