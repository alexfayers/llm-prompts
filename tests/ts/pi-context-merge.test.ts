import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, describe, test } from "node:test";
import { useEnv } from "./helpers.ts";
import { type Event, createWorktree, detectGate, land } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/merge.ts";

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-merge-"));
after(() => fs.rmSync(scratch, { recursive: true }));
useEnv({ PI_CONTEXT_TEST_CMD: "true" });

const git = (cwd: string, ...args: string[]) => execFileSync("git", args, { cwd, encoding: "utf8", stdio: "pipe" }).trim();
let repoCount = 0;

function newRepo() {
	const repo = path.join(scratch, `repo${repoCount++}`);
	fs.mkdirSync(repo);
	git(repo, "init", "-b", "main");
	git(repo, "config", "user.email", "t@example.com");
	git(repo, "config", "user.name", "t");
	commit(repo, "shared.txt", "one\ntwo\nthree\n");
	return fs.realpathSync(repo);
}

function commit(dir: string, file: string, text: string, message = `edit ${file}`) {
	fs.writeFileSync(path.join(dir, file), text);
	git(dir, "add", file);
	git(dir, "commit", "-m", message);
}

const subjects = (dir: string, range: string) => git(dir, "log", "--format=%s", range).split("\n").filter(Boolean);

const writer = (repo: string, name: string) => createWorktree(repo, path.join(scratch, "worktrees"), name);
const done: Event = { type: "fork-done" };
const never = async () => {
	throw new Error("the fork should not be asked");
};

describe("detectGate", () => {
	test("the test command comes from the repo's files, in order", () => {
		const cases: [Record<string, string>, string | undefined][] = [
			[{ justfile: "default:\n", "package.json": '{"scripts":{"test":"x"}}' }, "just"],
			[{ "package.json": '{"scripts": {"test": "vitest"}}', "pnpm-lock.yaml": "" }, "pnpm test"],
			[{ "package.json": '{"scripts":{"test":"x"}}', "yarn.lock": "" }, "yarn test"],
			[{ "package.json": '{"scripts":{"test":"x"}}' }, "npm test"],
			[{ "package.json": '{"scripts":{"build":"x"}}' }, undefined],
			[{ "pyproject.toml": "[tool.pytest.ini_options]\n", "uv.lock": "" }, "uv run pytest"],
			[{ "pyproject.toml": "[project]\n", "uv.lock": "", "tests/test_a.py": "" }, "uv run pytest"],
			[{ "pyproject.toml": "[project]\n", "uv.lock": "" }, undefined],
			[{ Makefile: "build:\n\ttrue\ntest:\n\ttrue\n" }, "make test"],
			[{ "Cargo.toml": "" }, "cargo test"],
			[{ "go.mod": "" }, "go test ./..."],
			[{}, undefined],
		];
		for (const [files, gate] of cases) {
			const dir = fs.mkdtempSync(path.join(scratch, "gate-"));
			for (const [file, text] of Object.entries(files)) {
				fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
				fs.writeFileSync(path.join(dir, file), text);
			}
			assert.equal(detectGate(dir), gate, JSON.stringify(files));
		}
	});
});

describe("landing", () => {
	test("a rebase conflict goes back to the same fork, which resolves it", async () => {
		const repo = newRepo();
		const tree = await writer(repo, "clash");
		commit(tree.path, "shared.txt", "one\nmine\nthree\n");
		commit(repo, "shared.txt", "one\ntheirs\nthree\n");
		const messages: string[] = [];
		const landing = await land({
			tree,
			first: done,
			resume: async (message) => {
				messages.push(message);
				assert.throws(() => git(tree.path, "rebase", "main"));
				fs.writeFileSync(path.join(tree.path, "shared.txt"), "one\nboth\nthree\n");
				git(tree.path, "add", "shared.txt");
				execFileSync("git", ["-c", "core.editor=true", "rebase", "--continue"], { cwd: tree.path, stdio: "pipe" });
				return { type: "fork-done" };
			},
		});
		assert.equal(messages.length, 1);
		assert.match(messages[0], /shared\.txt/);
		assert.equal(landing.state, "landed");
		assert.equal(fs.readFileSync(path.join(repo, "shared.txt"), "utf8"), "one\nboth\nthree\n");
	});

	test("a fork's fixup of its own commit lands folded into it, and lands as it is with folding off", async () => {
		const repo = newRepo();
		const tree = await writer(repo, "own");
		commit(tree.path, "own.txt", "draft");
		commit(tree.path, "own.txt", "final", "fixup! edit own.txt");
		const landing = await land({ tree, first: done, resume: never });
		assert.equal(landing.state, "landed");
		assert.deepEqual(subjects(repo, "main"), ["edit own.txt", "edit shared.txt"]);
		assert.equal(fs.readFileSync(path.join(repo, "own.txt"), "utf8"), "final");
		process.env.PI_CONTEXT_LAND_FOLD = "off";
		const loose = await writer(repo, "loose");
		commit(loose.path, "loose.txt", "draft");
		commit(loose.path, "loose.txt", "final", "fixup! edit loose.txt");
		assert.equal((await land({ tree: loose, first: done, resume: never })).state, "landed");
		delete process.env.PI_CONTEXT_LAND_FOLD;
		assert.deepEqual(subjects(repo, "main").slice(0, 2), ["fixup! edit loose.txt", "edit loose.txt"]);
	});

	test("a fork's fixup of an unpushed main commit folds into it, a pushed target keeps its fixup, and an older worktree still lands", async () => {
		const repo = newRepo();
		git(scratch, "init", "-q", "--bare", path.join(scratch, `${path.basename(repo)}.git`));
		git(repo, "remote", "add", "origin", path.join(scratch, `${path.basename(repo)}.git`));
		git(repo, "push", "-q", "-u", "origin", "main");
		const pushed = git(repo, "rev-parse", "main");
		commit(repo, "local.txt", "draft");
		const [fixer, older] = [await writer(repo, "fixer"), await writer(repo, "older")];
		commit(fixer.path, "local.txt", "final", "fixup! edit local.txt");
		commit(fixer.path, "shared.txt", "one\ntwo\nthree\nfour\n", "fixup! edit shared.txt");
		commit(older.path, "older.txt", "1");
		const landing = await land({ tree: fixer, first: done, resume: never });
		assert.equal(landing.state, "landed");
		assert.equal(landing.note, undefined);
		assert.equal(landing.sha, git(repo, "rev-parse", "HEAD"));
		assert.deepEqual(subjects(repo, "origin/main..main"), ["fixup! edit shared.txt", "edit local.txt"]);
		assert.equal(git(repo, "rev-parse", "origin/main"), pushed);
		assert.equal(git(repo, "show", "main~1:local.txt"), "final");
		const later = await land({ tree: older, first: done, resume: never });
		assert.equal(later.state, "landed");
		assert.deepEqual(subjects(repo, "origin/main..main"), ["edit older.txt", "fixup! edit shared.txt", "edit local.txt"]);
	});
});
