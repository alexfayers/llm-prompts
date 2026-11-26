import assert from "node:assert/strict";
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
	handle.dispose();
	fs.rmSync(root, { recursive: true });
});

test("dispose removes the directory once, and the exit handler is gone afterwards", () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-"));
	const before = process.listenerCount("exit");
	const { dir, dispose } = readOnlyAgentDir(root);
	assert.equal(process.listenerCount("exit"), before + 1);
	dispose();
	dispose();
	assert.equal(fs.existsSync(dir), false);
	assert.equal(process.listenerCount("exit"), before);
	fs.rmSync(root, { recursive: true });
});

test("a failed setup removes the directory it made", () => {
	const ownTmp = fs.mkdtempSync(path.join(os.tmpdir(), "agent-dir-tmp-"));
	const originalTmp = process.env.TMPDIR;
	process.env.TMPDIR = ownTmp;
	try {
		assert.throws(() => readOnlyAgentDir(path.join(ownTmp, "missing-agent-dir-x")));
		assert.deepEqual(fs.readdirSync(ownTmp), []);
	} finally {
		if (originalTmp === undefined) delete process.env.TMPDIR;
		else process.env.TMPDIR = originalTmp;
		fs.rmSync(ownTmp, { recursive: true });
	}
});
