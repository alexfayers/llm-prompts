import assert from "node:assert/strict";
import { join } from "node:path";
import { after, beforeEach, describe, mock, test } from "node:test";
import { promisify } from "node:util";
import { loadExtension, restoreMocks, useEnv, useMemoryFs } from "./helpers.ts";

const NOW = 2_000_000_000_000;
const MS_PER_SECOND = 1000;
const AGED_SECONDS = 1_577_836_800;
const WORKSPACE = "w1";
const HOUR_MS = 60 * 60 * 1000;
const GH_LIST = "pr list --state merged --author @me --limit 200 --json headRefName";
const mergedFor = (...branches: string[]) => JSON.stringify(branches.map((headRefName) => ({ headRefName })));

type Json = Record<string, any>;
type Worktree = { path: string; branch: string; head: string; dirty: boolean; reflog: number; merged: boolean; tip: number };
type World = { panes: Json[]; workspaces: Json[]; worktrees: Worktree[]; mainLine: string; remote?: string; gh?: string; herdr: string[]; ghCalls: string[] };

let world: World;
const memory = useMemoryFs();
const root = memory.root;

function run(command: string, args: string[], cwd?: string): string {
	const line = args.join(" ");
	if (command === "herdr") {
		world.herdr.push(line);
		if (line === "pane list") return JSON.stringify({ result: { panes: world.panes } });
		if (line === "pane current --current") return JSON.stringify({ result: { pane: { workspace_id: WORKSPACE } } });
		if (line === "workspace list") return JSON.stringify({ result: { workspaces: world.workspaces } });
		return "{}";
	}
	if (command === "ps") return "";
	if (command === "gh") {
		world.ghCalls.push(line);
		if (world.gh === undefined) throw new Error("gh failed");
		return world.gh;
	}
	const at = (head: string) => world.worktrees.find((worktree) => worktree.head === head || worktree.path === head)!;
	switch (args[0]) {
		case "worktree":
			return [`worktree ${root}\nHEAD aaa\n${world.mainLine}`, ...world.worktrees.map((w) => `worktree ${w.path}\nHEAD ${w.head}\n${w.branch ? `branch refs/heads/${w.branch}` : "detached"}`)].join("\n\n");
		case "remote":
			if (!world.remote) throw new Error("no origin");
			return world.remote;
		case "status":
			return at(cwd!).dirty ? " M base" : "";
		case "reflog":
			return Array(world.worktrees.find((w) => `refs/heads/${w.branch}` === args.at(-1))!.reflog).fill("a").join("\n");
		case "for-each-ref":
			return at(args[2]).merged ? "refs/heads/main\n" : "";
		case "log":
			return String(at(cwd!).tip);
	}
	throw new Error(`unexpected ${command} ${line}`);
}

const execFile = Object.assign(() => {}, {
	[promisify.custom]: async (command: string, args: string[], options: { cwd?: string }) => ({ stdout: run(command, args, options.cwd), stderr: "" }),
});

const load = () => loadExtension("pane-reaper", { agentDir: join(root, "agent"), mocks: { "node:child_process": { execFile } } });

function pane(id: string, tab: string, { cwd, workspace = "w1" }: { cwd?: string; workspace?: string } = {}): Json {
	return { pane_id: id, tab_id: tab, workspace_id: workspace, ...(cwd && { cwd }) };
}

function addWorktree(name: string, options: Partial<Worktree> & { fresh?: boolean } = {}): Worktree {
	const { fresh, ...rest } = options;
	const worktree = { path: join(root, "worktrees", name), branch: `feat/${name}`, head: `head-${name}`, dirty: false, reflog: 2, merged: true, tip: AGED_SECONDS, ...rest };
	memory.mkdir(worktree.path, fresh ? Date.now() : AGED_SECONDS * MS_PER_SECOND);
	world.worktrees.push(worktree);
	return worktree;
}

const declareWorkspace = (id: string, worktree: Worktree) => world.workspaces.push({ workspace_id: id, worktree: { checkout_path: worktree.path } });
const sweepWorktrees = async () => (await load()).module.sweepWorktrees();
const settle = () => new Promise(setImmediate);
const notices = (ext: Awaited<ReturnType<typeof load>>) => ext.ctx.notices;

function setEnv(overrides: Record<string, string | undefined> = {}) {
	for (const [name, value] of Object.entries({ HERDR_ENV: "1", ...overrides })) {
		if (value === undefined) delete process.env[name];
		else process.env[name] = value;
	}
}

async function start(ext: Awaited<ReturnType<typeof load>>, times = 1) {
	for (let i = 0; i < times; i++) {
		await ext.fire("session_start");
		await settle();
	}
	await ext.fire("session_shutdown");
}

async function command(ext: Awaited<ReturnType<typeof load>>, ...args: string[]) {
	const ctx = ext.makeCtx();
	for (const arg of args) await ext.runCommand("pane-reaper", arg, ctx);
	return ctx.notices;
}

useEnv({ PI_SUBAGENT_CHILD: undefined, HERDR_ENV: undefined });
beforeEach(() => {
	world = { panes: [], workspaces: [], worktrees: [], mainLine: "branch refs/heads/main", herdr: [], ghCalls: [] };
});
after(restoreMocks);

describe("sweepWorktrees", () => {
	test("reports a merged clean worktree with a pane-less workspace as a candidate without opening or removing anything", async () => {
		const done = addWorktree("done");
		declareWorkspace("w9", done);
		const result = await sweepWorktrees();
		assert.deepEqual(result.candidates.map((w: Json) => [w.path, w.branch]), [[done.path, "feat/done"]]);
		assert.deepEqual(result.kept, []);
		assert.deepEqual(world.herdr, ["pane list", "workspace list"]);
	});

	for (const [label, overrides, reason] of [
		["tracked or untracked file present", { dirty: true }, "has uncommitted or untracked files"],
		["branch has an unmerged commit", { merged: false }, "branch is not merged into main"],
		["head is detached", { branch: "" }, "head is detached"],
		["branch is main", { branch: "main" }, "branch is main"],
		["branch never had a commit of its own", { reflog: 1 }, "branch has no commits of its own"],
		["tip committed recently", { tip: Math.floor(Date.now() / 1000) - 3600 }, "changed in the last 24 hours"],
		["directory touched recently", { fresh: true }, "changed in the last 24 hours"],
	] as const) {
		test(`keeps a worktree: ${label}`, async () => {
			const wip = addWorktree("wip", overrides);
			declareWorkspace("w9", wip);
			const result = await sweepWorktrees();
			assert.deepEqual(result.candidates, []);
			assert.deepEqual(result.kept.map((w: Json) => [w.path, w.reason]), [[wip.path, reason]]);
		});
	}

	for (const mainLine of ["branch refs/heads/other", "detached"]) {
		test(`judges the worktree on its own state with main checkout "${mainLine}"`, async () => {
			world.mainLine = mainLine;
			const done = addWorktree("done");
			const result = await sweepWorktrees();
			assert.deepEqual(result.candidates.map((w: Json) => w.path), [done.path]);
			assert.deepEqual(result.kept, []);
		});
	}

	for (const [label, setup, reason] of [
		["agent cwd is in a subdirectory", (busy: Worktree) => (world.panes = [pane("w1:p2", "w1:t2", { cwd: join(busy.path, "src") })]), "a pane is still inside it"],
		["workspace has a pane elsewhere", (busy: Worktree) => ((world.panes = [pane("w9:p1", "w9:t1", { workspace: "w9", cwd: root })]), declareWorkspace("w9", busy)), "its Herdr workspace is still open"],
	] as const) {
		test(`keeps a worktree in use: ${label}`, async () => {
			const busy = addWorktree("busy");
			setup(busy);
			const result = await sweepWorktrees();
			assert.deepEqual(result.candidates, []);
			assert.deepEqual(result.kept.map((w: Json) => [w.path, w.reason]), [[busy.path, reason]]);
		});
	}

});

describe("sweepWorktrees confirms squash merges on GitHub only", () => {
	const squashed = () => addWorktree("squashed", { merged: false });

	for (const remote of ["https://github.com/owner/repo.git", "git@github.com:owner/repo.git", "ssh://git@github.com/owner/repo.git"]) {
		test(`GitHub remote ${remote} with a merged pull request is a candidate`, async () => {
			world.remote = remote;
			world.gh = mergedFor("feat/squashed");
			const branch = squashed();
			const result = await sweepWorktrees();
			assert.deepEqual(result.candidates.map((w: Json) => w.path), [branch.path]);
			assert.deepEqual(result.kept, []);
			assert.deepEqual(world.ghCalls, [GH_LIST]);
		});
	}

	for (const remote of [undefined, "https://example.com/github.com/owner/repo", "https://notgithub.com/owner/repo"]) {
		test(`other remote ${remote} never calls gh and the branch is kept unmerged`, async () => {
			world.remote = remote;
			world.gh = mergedFor("feat/squashed");
			squashed();
			const result = await sweepWorktrees();
			assert.deepEqual(result.candidates, []);
			assert.deepEqual(result.kept.map((w: Json) => w.reason), ["branch is not merged into main"]);
			assert.deepEqual(world.ghCalls, []);
		});
	}

	test("one gh call covers every worktree and matches branches locally", async () => {
		world.remote = "https://github.com/owner/repo";
		world.gh = mergedFor("feat/a", "feat/c");
		const [a, b, c] = ["a", "b", "c"].map((name) => addWorktree(name, { merged: false }));
		const result = await sweepWorktrees();
		assert.deepEqual(result.candidates.map((w: Json) => w.path), [a.path, c.path]);
		assert.deepEqual(result.kept.map((w: Json) => w.path), [b.path]);
		assert.deepEqual(world.ghCalls, [GH_LIST]);
	});

	test("a merged branch is remembered across sweeps without another gh call", async () => {
		world.remote = "https://github.com/owner/repo";
		world.gh = mergedFor("feat/squashed");
		squashed();
		const ext = await load();
		await ext.module.sweepWorktrees();
		world.gh = undefined;
		const result = await ext.module.sweepWorktrees();
		assert.equal(result.candidates.length, 1);
		assert.equal(world.ghCalls.length, 1);
	});

	test("a not-merged branch is rechecked only after an hour", async () => {
		world.remote = "https://github.com/owner/repo";
		world.gh = "[]";
		squashed();
		const now = mock.method(Date, "now", () => NOW);
		const ext = await load();
		await ext.module.sweepWorktrees();
		now.mock.mockImplementation(() => NOW + HOUR_MS - 1);
		await ext.module.sweepWorktrees();
		assert.equal(world.ghCalls.length, 1);
		now.mock.mockImplementation(() => NOW + HOUR_MS);
		await ext.module.sweepWorktrees();
		assert.equal(world.ghCalls.length, 2);
	});

	test("a gh error is not remembered as not merged and is not retried within the sweep", async () => {
		world.remote = "https://github.com/owner/repo";
		world.gh = undefined;
		addWorktree("a", { merged: false });
		addWorktree("b", { merged: false });
		const ext = await load();
		await ext.module.sweepWorktrees();
		assert.equal(world.ghCalls.length, 1);
		world.gh = mergedFor("feat/a");
		const result = await ext.module.sweepWorktrees();
		assert.deepEqual(result.candidates.map((w: Json) => w.branch), ["feat/a"]);
		assert.equal(world.ghCalls.length, 2);
	});

	for (const [label, gh] of [["no merged pull request", "[]"], ["gh fails", undefined]] as const) {
		test(`GitHub branch is kept: ${label}`, async () => {
			world.remote = "https://github.com/owner/repo";
			world.gh = gh;
			squashed();
			const result = await sweepWorktrees();
			assert.deepEqual(result.candidates, []);
			assert.deepEqual(result.kept.map((w: Json) => w.reason), ["branch is not merged into main"]);
		});
	}
});

describe("session start", () => {
	for (const [label, env, config] of [
		["in a subagent", { PI_SUBAGENT_CHILD: "1" }, undefined],
		["outside Herdr", { HERDR_ENV: undefined }, undefined],
		["when disabled", {}, '{"enabled": false}'],
	] as const) {
		test(`does not sweep ${label}`, async () => {
			setEnv(env);
			if (config) memory.write(join(root, "agent/pane-reaper.json"), config);
			await start(await load());
			assert.deepEqual(world.herdr, []);
		});
	}

	test("reports a candidate once and the kept worktrees once per change of the kept set", async () => {
		setEnv();
		addWorktree("wip", { merged: false });
		const settling = addWorktree("settling", { fresh: true });
		declareWorkspace("w9", settling);
		const ext = await load();
		await start(ext, 2);
		memory.touch(settling.path, AGED_SECONDS * MS_PER_SECOND);
		await start(ext, 2);
		assert.deepEqual(notices(ext).map(([text]) => text), [
			"pane-reaper kept 2 worktrees (see /pane-reaper)",
			`pane-reaper: worktree ${settling.path} (feat/settling): merged into main and clean. Safe to remove`,
			"pane-reaper kept 1 worktree (see /pane-reaper)",
		]);
	});
});

describe("/pane-reaper", () => {
	test("check now says when there is nothing to report", async () => {
		assert.deepEqual(await command(await load(), ""), [["pane-reaper: nothing to report", "info"]]);
	});

	test("check now reports candidate and kept worktrees", async () => {
		const done = addWorktree("done");
		const wip = addWorktree("wip", { merged: false });
		declareWorkspace("w9", done);
		const result = await command(await load(), "");
		assert.deepEqual(result.map(([, level]) => level), ["info", "info"]);
		assert.match(result[0][0], new RegExp(`${done.path}.*Safe to remove`));
		assert.match(result[1][0], new RegExp(`${wip.path}.*not merged`));
	});

	test("on and off rewrite the config keeping other keys", async () => {
		const file = join(root, "agent/pane-reaper.json");
		memory.write(file, '{"intervalSeconds": 60}');
		const ext = await load();
		await command(ext, "off");
		assert.deepEqual(JSON.parse(memory.read(file)), { intervalSeconds: 60, enabled: false });
		await command(ext, "on");
		assert.deepEqual(JSON.parse(memory.read(file)), { intervalSeconds: 60, enabled: true });
	});
});

test("config interval is clamped", async () => {
	const { readConfig } = (await load()).module;
	const file = join(root, "pane-reaper.json");
	memory.write(file, JSON.stringify({ enabled: false, intervalSeconds: 1 }));
	assert.deepEqual(readConfig(file), { enabled: false, intervalSeconds: 10 });
});

test("a marked agent process whose pane is dead in this workspace is killed", async () => {
	const orphan = { pid: 445, uid: 501, ppid: 1, pgid: 4000, state: "S", cpuPercent: 0, cpuSeconds: 1, started: "Wed Oct 14 09:55:00 2026", command: "/usr/bin/some-mcp-server --stdio" };
	const deps = {
		list: async () => [orphan],
		recheck: async () => orphan,
		kill: () => {},
		marker: async () => ({ agent: true, paneId: "w1:p1" }),
		livePaneIds: async () => ["w1:p2"],
	};
	const result = await (await load()).module.sweepOrphans({ selfPids: [9000], uid: 501, workspaceId: WORKSPACE }, deps);
	assert.deepEqual(result.killed.map((killed: Json) => killed.proc.pid), [445]);
});
