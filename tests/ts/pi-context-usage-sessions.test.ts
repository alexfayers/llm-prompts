import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { KEPT_MAX_AGE_MS, migrateUsageSessions, pruneKept, retainSession } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/usage-sessions.ts";

const jsonl = (entries: unknown[]) => entries.map((entry) => JSON.stringify(entry)).join("\n") + "\n";
const header = (id: string) => ({ type: "session", version: 3, id });
const message = (id: string, parentId: string | null, role = "assistant") => ({ type: "message", id, parentId, message: { role, content: [], usage: { input: 1 } } });
const root = () => fs.mkdtempSync(path.join(os.tmpdir(), "fork-usage-"));

test("retained warm sessions archive every snapshot and account only for child entries across resumes", async () => {
	const dir = root();
	try {
		const source = path.join(dir, "seed.jsonl");
		const inherited = message("parent", null);
		const own = message("child", "parent");
		const original = jsonl([header("fork"), inherited, own]);
		fs.writeFileSync(source, original);
		const kept = await retainSession(source, "reader-run.jsonl", "parent", dir);
		assert.equal(fs.readFileSync(kept.archive, "utf8"), original);
		assert.deepEqual(fs.readFileSync(kept.usage, "utf8").trim().split("\n").map((line) => JSON.parse(line)).slice(1), [{ ...own, parentId: null }]);
		const resumed = original + jsonl([message("next", "child")]);
		fs.writeFileSync(source, resumed);
		const later = await retainSession(source, "reader-run.jsonl", "parent", dir);
		assert.equal(fs.readdirSync(path.dirname(kept.archive)).length, 2);
		assert.equal(fs.readFileSync(kept.archive, "utf8"), original);
		assert.equal(fs.readFileSync(later.archive, "utf8"), resumed);
		assert.equal(fs.readFileSync(later.usage, "utf8").trim().split("\n").length, 3);
		await assert.rejects(() => retainSession(source, "reader-run.jsonl", "missing", dir), /inherited/);
		assert.equal(fs.readFileSync(later.usage, "utf8").trim().split("\n").length, 3);
		fs.writeFileSync(source, jsonl([header("different"), own]));
		await assert.rejects(() => retainSession(source, "reader-run.jsonl", undefined, dir), /collision/);
		const cold = await retainSession(source, "cold-run.jsonl", undefined, dir);
		assert.equal(fs.readFileSync(cold.usage, "utf8").trim().split("\n").length, 2);
		fs.writeFileSync(source, jsonl([header("nested"), inherited, own, message("nested-own", "child")]));
		const nested = await retainSession(source, "nested-run.jsonl", "child", dir);
		assert.equal(fs.readFileSync(nested.usage, "utf8").trim().split("\n").length, 2);
	} finally { fs.rmSync(dir, { recursive: true }); }
});

test("concurrent retention recovers a dead or uninitialized owner's lock without losing either snapshot", async () => {
	const dir = root();
	try {
		const lock = path.join(dir, "sessions", "pi-context", ".usage-lock");
		fs.mkdirSync(lock, { recursive: true });
		const deadPid = execFileSync(process.execPath, ["-p", "process.pid"], { encoding: "utf8" }).trim();
		fs.writeFileSync(path.join(lock, `${deadPid}-00000000-0000-0000-0000-000000000000`), "");
		const sources = ["first", "second"].map((name) => {
			const file = path.join(dir, `${name}.jsonl`);
			fs.writeFileSync(file, jsonl([header(name), message(name, null)]));
			return file;
		});
		const copies = await Promise.all(sources.map((file, at) => retainSession(file, `cold-${at}.jsonl`, undefined, dir)));
		for (const [at, copy] of copies.entries()) assert.deepEqual(fs.readFileSync(copy.archive), fs.readFileSync(sources[at]));
		assert.equal(fs.existsSync(lock), false);
		fs.mkdirSync(lock);
		await retainSession(sources[0], "cold-0.jsonl", undefined, dir);
		assert.equal(fs.existsSync(lock), false);
	} finally { fs.rmSync(dir, { recursive: true }); }
});

test("migration keeps a transcript that a resumed fork replaced after migration read it", async (t) => {
	const dir = root();
	try {
		const kept = path.join(dir, "sessions", "pi-context");
		fs.mkdirSync(kept, { recursive: true });
		const inherited = message("parent", null);
		const prompt = { ...message("prompt", "parent", "user"), message: { role: "user", content: "You are the delegate that the conversation above asked to fork, so do not call fork." } };
		const original = jsonl([header("fork"), inherited, prompt, message("own", "prompt")]);
		const resumed = original + jsonl([message("resumed", "own")]);
		fs.writeFileSync(path.join(dir, "sessions", "main.jsonl"), jsonl([header("main"), inherited]));
		const file = path.join(kept, "reader-12345678.jsonl");
		fs.writeFileSync(file, original);
		const link = fs.linkSync;
		t.mock.method(fs, "linkSync", (...args: any[]) => {
			Reflect.apply(link, fs, args);
			if (fs.readFileSync(file, "utf8") !== original) return;
			fs.writeFileSync(`${file}.tmp`, resumed);
			fs.renameSync(`${file}.tmp`, file);
		});
		assert.equal((await migrateUsageSessions(dir, true)).changes.length, 0);
		assert.equal(fs.readFileSync(file, "utf8"), resumed);
	} finally { fs.rmSync(dir, { recursive: true }); }
});

test("migration skips a transcript that another process projected while it indexed parents", async (t) => {
	const dir = root();
	try {
		const kept = path.join(dir, "sessions", "pi-context");
		fs.mkdirSync(kept, { recursive: true });
		const inherited = message("parent", null);
		const prompt = { ...message("prompt", "parent", "user"), message: { role: "user", content: "You are the delegate that the conversation above asked to fork, so do not call fork." } };
		fs.writeFileSync(path.join(dir, "sessions", "main.jsonl"), jsonl([header("main"), inherited]));
		const file = path.join(kept, "reader-12345678.jsonl");
		fs.writeFileSync(file, jsonl([header("fork"), inherited, prompt, message("own", "prompt")]));
		const projected = jsonl([{ ...header("fork"), piContextUsage: { version: 1, sourceHash: "0".repeat(64) } }, inherited]);
		const stream = fs.createReadStream;
		t.mock.method(fs, "createReadStream", (...args: any[]) => {
			fs.writeFileSync(`${file}.tmp`, projected);
			fs.renameSync(`${file}.tmp`, file);
			return Reflect.apply(stream, fs, args);
		});
		assert.equal((await migrateUsageSessions(dir, true)).changes.length, 0);
		assert.equal(fs.readFileSync(file, "utf8"), projected);
	} finally { fs.rmSync(dir, { recursive: true }); }
});

test("migration skips a transcript replaced during either planning read", async (t) => {
	for (const replacedRead of [1, 2]) {
		const dir = root();
		try {
			const kept = path.join(dir, "sessions", "pi-context");
			fs.mkdirSync(kept, { recursive: true });
			const inherited = message("parent", null);
			const prompt = { ...message("prompt", "parent", "user"), message: { role: "user", content: "You are the delegate that the conversation above asked to fork, so do not call fork." } };
			fs.writeFileSync(path.join(dir, "sessions", "main.jsonl"), jsonl([header("main"), inherited]));
			const file = path.join(kept, "reader-12345678.jsonl");
			const original = jsonl([header("fork"), inherited, prompt, message("own", "prompt")]);
			const resumed = original + jsonl([message("resumed", "own")]);
			fs.writeFileSync(file, original);
			const read = fs.promises.readFile;
			let reads = 0;
			const mock = t.mock.method(fs.promises, "readFile", async (...args: any[]) => {
				const data = await Reflect.apply(read, fs.promises, args);
				if (args[0] === file && ++reads === replacedRead) {
					fs.writeFileSync(`${file}.tmp`, resumed);
					fs.renameSync(`${file}.tmp`, file);
				}
				return data;
			});
			assert.equal((await migrateUsageSessions(dir, true)).changes.length, 0);
			assert.equal(fs.readFileSync(file, "utf8"), resumed);
			mock.mock.restore();
		} finally { fs.rmSync(dir, { recursive: true }); }
	}
});

test("legacy migration tolerates unbilled metadata drift and whole-file clones but blocks billed or usage changes", async () => {
	const dir = root();
	try {
		const sessions = path.join(dir, "sessions");
		const kept = path.join(sessions, "pi-context");
		fs.mkdirSync(kept, { recursive: true });
		const billedEntry = message("a1", null);
		const tool = { type: "message", id: "t1", parentId: "a1", message: { role: "toolResult", content: [], details: { pattern: "long" } } };
		const drifted = { ...tool, message: { ...tool.message, details: { pattern: "short" } } };
		const prompt = { ...message("prompt", "t1", "user"), message: { role: "user", content: "You are the delegate that the conversation above asked to fork, so do not call fork." } };
		fs.writeFileSync(path.join(sessions, "main.jsonl"), jsonl([header("main"), billedEntry, tool]));
		const file = path.join(kept, "reader-12345678.jsonl");
		const lines = (data: string) => data.trim().split("\n").length;
		const fork = (...entries: unknown[]) => fs.writeFileSync(file, jsonl([header("fork"), ...entries]));
		fork(billedEntry, drifted, message("system", "t1", "system"), prompt, message("own", "prompt"));
		assert.equal((await migrateUsageSessions(dir)).changes[0].inherited, "t1");
		fork(billedEntry, tool);
		const original = fs.readFileSync(file, "utf8");
		const clone = await migrateUsageSessions(dir, true);
		assert.equal(fs.readFileSync(clone.changes[0].archive!, "utf8"), original);
		assert.equal(lines(fs.readFileSync(file, "utf8")), 1);
		const cases: [unknown[], RegExp][] = [
			[[{ ...billedEntry, message: { ...billedEntry.message, usage: { input: 2 } } }, drifted, prompt], /billed ancestry/],
			[[billedEntry, { ...drifted, message: { ...drifted.message, usage: { input: 1 } } }, prompt, message("own", "prompt")], /billed ancestry/],
			[[{ ...billedEntry, message: { ...billedEntry.message, usage: { input: 2 } } }, tool], /no identifiable boundary/],
		];
		for (const [entries, reason] of cases) {
			fork(...entries);
			assert.match((await migrateUsageSessions(dir)).blocked[0]?.reason ?? "", reason);
		}
		fork(billedEntry, tool, message("a2", "t1"), prompt, message("own", "prompt"));
		assert.match((await migrateUsageSessions(dir)).blocked[0]?.reason ?? "", /lineage is missing/);
		fork(billedEntry, tool, { ...prompt, message: { role: "user", content: "You answer one side question for the user. Read-only." } }, message("own", "prompt"));
		assert.equal((await migrateUsageSessions(dir)).changes[0]?.inherited, "t1");
		fs.writeFileSync(path.join(sessions, "copy.jsonl"), jsonl([header("copy"), billedEntry, { ...tool, message: { ...tool.message, details: { pattern: "other" } } }]));
		fork(billedEntry, drifted, prompt);
		assert.match((await migrateUsageSessions(dir)).blocked[0]?.reason ?? "", /content is ambiguous/);
	} finally { fs.rmSync(dir, { recursive: true }); }
});

test("legacy migration is dry-run first, keeps originals and bills colliding IDs in unrelated sessions", async () => {
	const dir = root();
	try {
		const sessions = path.join(dir, "sessions");
		const kept = path.join(sessions, "pi-context");
		fs.mkdirSync(kept, { recursive: true });
		const inherited = message("same-id", null);
		const prompt = { ...message("prompt", "same-id", "user"), message: { role: "user", content: [{ type: "text", text: "You are the delegate that the conversation above asked to fork, so do not call fork. You are read-only." }] } };
		const main = jsonl([header("main"), inherited]);
		const unrelated = jsonl([header("other"), { ...inherited, message: { ...inherited.message, usage: { input: 5 } } }]);
		fs.writeFileSync(path.join(sessions, "main.jsonl"), main);
		fs.writeFileSync(path.join(sessions, "other.jsonl"), unrelated);
		const system = message("system", "same-id", "system");
		const original = jsonl([header("fork"), inherited, system, prompt, message("own", "prompt")]);
		const file = path.join(kept, "reader-12345678.jsonl");
		fs.writeFileSync(file, original);
		assert.equal((await migrateUsageSessions(dir)).changes.length, 1);
		assert.equal(fs.readFileSync(file, "utf8"), original);
		assert.equal(fs.existsSync(path.join(dir, "pi-context")), false);
		const applied = await migrateUsageSessions(dir, true);
		assert.equal(fs.readFileSync(applied.changes[0].archive!, "utf8"), original);
		assert.equal(fs.readFileSync(file, "utf8").trim().split("\n").length, 4);
		assert.equal((await migrateUsageSessions(dir, true)).changes.length, 0);
		assert.equal(fs.readFileSync(path.join(sessions, "other.jsonl"), "utf8"), unrelated);
		fs.writeFileSync(file, original);
		fs.writeFileSync(path.join(sessions, "clone.jsonl"), jsonl([header("clone"), inherited]));
		assert.equal((await migrateUsageSessions(dir)).blocked.length, 0);
		assert.equal((await migrateUsageSessions(dir, true)).changes.length, 1);
		fs.unlinkSync(path.join(sessions, "clone.jsonl"));
		fs.writeFileSync(path.join(sessions, "unrelated-partial.jsonl"), jsonl([header("active-other")]) + '{"type":');
		fs.writeFileSync(file, original);
		assert.equal((await migrateUsageSessions(dir)).blocked.length, 0);
		fs.writeFileSync(path.join(sessions, "main.jsonl"), main + '{"type":');
		assert.match((await migrateUsageSessions(dir)).blocked[0].reason, /Unreadable parent/);
		await assert.rejects(() => migrateUsageSessions(dir, true), /Migration blocked/);
		assert.equal(fs.readFileSync(file, "utf8"), original);
		fs.writeFileSync(path.join(sessions, "main.jsonl"), main);
		fs.writeFileSync(file, jsonl([header("partial"), inherited, message("partial-own", "same-id")]));
		assert.match((await migrateUsageSessions(dir)).blocked[0].reason, /no identifiable boundary/);
		await assert.rejects(() => migrateUsageSessions(dir, true), /Migration blocked/);
	} finally { fs.rmSync(dir, { recursive: true }); }
});

test("pruneKept drops old archives except those a recent usage session needs, and runs once a day", async () => {
	const dir = root();
	try {
		const source = path.join(dir, "seed.jsonl");
		const age = (file: string, ms: number) => fs.utimesSync(file, new Date(Date.now() - ms), new Date(Date.now() - ms));
		const old = KEPT_MAX_AGE_MS + 1000;
		fs.writeFileSync(source, jsonl([header("stale"), message("a", null)]));
		const stale = await retainSession(source, "stale-run.jsonl", undefined, dir);
		fs.writeFileSync(source, jsonl([header("busy"), message("b", null)]));
		const first = await retainSession(source, "busy-run.jsonl", undefined, dir);
		fs.writeFileSync(source, jsonl([header("busy"), message("b", null), message("c", "b")]));
		const current = await retainSession(source, "busy-run.jsonl", undefined, dir);
		for (const file of [stale.archive, first.archive, current.archive, stale.usage]) age(file, old);
		const unreferenced = path.join(dir, "pi-context", "kept", `${"0".repeat(64)}.jsonl`);
		fs.writeFileSync(unreferenced, "x");
		age(unreferenced, old);
		assert.equal(pruneKept(dir), true);
		assert.deepEqual(fs.readdirSync(path.dirname(stale.archive)), [path.basename(current.archive)]);
		assert.equal(fs.existsSync(stale.usage), true);
		assert.equal(pruneKept(dir), false);
		assert.equal(pruneKept(dir, Date.now() + 25 * 60 * 60_000), true);
	} finally { fs.rmSync(dir, { recursive: true }); }
});
