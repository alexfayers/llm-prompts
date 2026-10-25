import assert from "node:assert/strict";
import { join } from "node:path";
import { after, beforeEach, describe, test } from "node:test";
import { promisify } from "node:util";
import { loadExtension, restoreMocks, useEnv, useMemoryFs } from "./helpers.ts";

const MINUTE_MS = 60_000;
const NOW = 2_000_000_000_000;
const OLD = NOW - 30 * MINUTE_MS;
const MS_PER_SECOND = 1000;
const AGED_SECONDS = 1_577_836_800;
const LIVE_OWNER = "01a00000-0000-7000-8000-00000000000a";
const DEAD_OWNER = "01a00000-0000-7000-8000-00000000000d";
const SELF = "01a00000-0000-7000-8000-0000000000e5";
const WORKSPACE = "w1";
const REQUEST = "f42f4a53-9d3c-435b-95b4-509250f47ae5";
const GITHUB_PR = '[{"number": 7}]';

type Json = Record<string, any>;
type Worktree = { path: string; branch: string; head: string; dirty: boolean; reflog: number; merged: boolean; tip: number };
type World = { panes: Json[]; workspaces: Json[]; worktrees: Worktree[]; mainLine: string; remote?: string; gh?: string; failClose: boolean; herdr: string[]; ghCalls: string[] };

let world: World;
const memory = useMemoryFs();
const root = memory.root;
const mailboxes = join(root, "agent/pi-herdsman/runtime/mailboxes-v5");

function run(command: string, args: string[], cwd?: string): string {
	const line = args.join(" ");
	if (command === "herdr") {
		world.herdr.push(line);
		if (line === "pane list") return JSON.stringify({ result: { panes: world.panes } });
		if (line === "pane current --current") return JSON.stringify({ result: { pane: { workspace_id: WORKSPACE } } });
		if (line === "workspace list") return JSON.stringify({ result: { workspaces: world.workspaces } });
		if (args[1] === "close" && world.failClose) throw new Error("close failed");
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

function pane(id: string, tab: string, options: { status?: string; managed?: boolean; started?: number; request?: string; session?: string; cwd?: string; workspace?: string } = {}): Json {
	const { status = "idle", managed = true, started = OLD, request = REQUEST, session, cwd, workspace = "w1" } = options;
	return {
		pane_id: id,
		tab_id: tab,
		agent_status: status,
		workspace_id: workspace,
		tokens: { request, started: String(started), ...(managed && { managed: "1" }) },
		...(cwd && { cwd }),
		...(session && { agent_session: { value: `/sessions/2026-10-10T20-11-24-885Z_${session}.jsonl` } }),
	};
}

const recent = (options: Parameters<typeof pane>[2] = {}) => ({ started: Date.now() - 30 * MINUTE_MS, ...options });

function addState(paneId: string, { owner = DEAD_OWNER, completed = true, version = 5 } = {}) {
	const state = { version, ownerSessionId: owner, paneId, ...(completed ? { completedRequestId: REQUEST } : { activeRequestId: REQUEST }) };
	memory.writeMailboxState(join(root, "agent"), paneId.replace(":", "_"), state);
}

function addWorktree(name: string, options: Partial<Worktree> & { fresh?: boolean } = {}): Worktree {
	const { fresh, ...rest } = options;
	const worktree = { path: join(root, "worktrees", name), branch: `feat/${name}`, head: `head-${name}`, dirty: false, reflog: 2, merged: true, tip: AGED_SECONDS, ...rest };
	memory.mkdir(worktree.path, fresh ? Date.now() : AGED_SECONDS * MS_PER_SECOND);
	world.worktrees.push(worktree);
	return worktree;
}

const declareWorkspace = (id: string, worktree: Worktree) => world.workspaces.push({ workspace_id: id, worktree: { checkout_path: worktree.path } });
const sweep = (ext: Awaited<ReturnType<typeof load>>) => ext.module.sweep({ now: NOW, graceSeconds: 900, selfSessionId: SELF, workspaceId: WORKSPACE });
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

useEnv({ PI_HERDSMAN_MAILBOX: undefined, PI_SUBAGENT_CHILD: undefined, HERDR_ENV: undefined, PI_SESSION_ID: SELF });
beforeEach(() => {
	memory.mkdir(mailboxes);
	world = { panes: [], workspaces: [], worktrees: [], mainLine: "branch refs/heads/main", failClose: false, herdr: [], ghCalls: [] };
});
after(restoreMocks);

describe("sweep closes a finished orphan", () => {
	test("done managed pane of a dead owner past grace", async () => {
		world.panes = [pane("w1:p2", "w1:t2", { status: "done" })];
		addState("w1:p2");
		const result = await sweep(await load());
		assert.deepEqual(result.closed.map((c: Json) => c.paneId), ["w1:p2"]);
		assert.deepEqual(result.asked, []);
		assert.deepEqual(world.herdr, ["pane list", "tab close w1:t2"]);
	});

	test("a pane sharing its tab closes alone and a lone pane closes its tab", async () => {
		world.panes = [pane("w1:p2", "w1:t2"), pane("w1:p3", "w1:t2", { managed: false }), pane("w1:p4", "w1:t4")];
		addState("w1:p2");
		addState("w1:p4");
		await sweep(await load());
		assert.deepEqual(world.herdr, ["pane list", "pane close w1:p2", "tab close w1:t4"]);
	});

	test("a failed close is reported and the sweep goes on", async () => {
		world.failClose = true;
		world.panes = [pane("w1:p2", "w1:t2"), pane("w1:p4", "w1:t4")];
		addState("w1:p2");
		addState("w1:p4");
		const result = await sweep(await load());
		assert.deepEqual(result.closed, []);
		assert.deepEqual(result.asked.map((c: Json) => [c.paneId, c.reason]), [["w1:p2", "closing it failed"], ["w1:p4", "closing it failed"]]);
	});
});

describe("sweep ignores panes that are not orphans", () => {
	const orphan = () => pane("w1:p2", "w1:t2");
	for (const [label, panes, state] of [
		["owner pane is live", () => [orphan(), pane("w1:p1", "w1:t1", { managed: false, session: LIVE_OWNER })], { owner: LIVE_OWNER }],
		["owner is this session", () => [orphan()], { owner: SELF }],
		["pane is not managed", () => [pane("w1:p2", "w1:t2", { managed: false })], {}],
		["pane is in another workspace", () => [pane("w2:p2", "w2:t2", { workspace: "w2" })], {}],
		["pane is inside the grace period", () => [pane("w1:p2", "w1:t2", { started: NOW - 5 * MINUTE_MS })], {}],
	] as const) {
		test(label, async () => {
			world.panes = panes();
			addState("w1:p2", state);
			assert.deepEqual(await sweep(await load()), { closed: [], asked: [] });
			assert.deepEqual(world.herdr, ["pane list"]);
		});
	}
});

describe("sweep only asks about other flagged panes", () => {
	for (const [label, flagged, state] of [
		["pane is still working", () => pane("w1:p2", "w1:t2", { status: "working" }), {}],
		["task has not finished", () => pane("w1:p2", "w1:t2"), { completed: false }],
		["pane moved on to another request", () => pane("w1:p2", "w1:t2", { request: "another-request" }), {}],
		["launch time is unknown", () => ({ ...pane("w1:p2", "w1:t2"), tokens: { managed: "1" } }), {}],
		["pane has no state file", () => pane("w1:p2", "w1:t2"), undefined],
	] as const) {
		test(label, async () => {
			world.panes = [flagged()];
			if (state) addState("w1:p2", state);
			const result = await sweep(await load());
			assert.deepEqual(result.asked.map((c: Json) => [c.paneId, Boolean(c.reason)]), [["w1:p2", true]]);
			assert.deepEqual(result.closed, []);
			assert.deepEqual(world.herdr, ["pane list"]);
		});
	}
});

describe("sweep stays silent on unknown herdsman state", () => {
	for (const [label, break_] of [
		["unknown version", () => addState("w1:p3", { version: 6 })],
		["corrupt file", () => memory.write(join(mailboxes, "w1_p3/state.json"), "{not json")],
		["missing directory", () => memory.remove(mailboxes)],
	] as const) {
		test(label, async () => {
			world.panes = [pane("w1:p2", "w1:t2"), pane("w1:p3", "w1:t3")];
			addState("w1:p2");
			addState("w1:p3");
			break_();
			assert.deepEqual(await sweep(await load()), { closed: [], asked: [] });
			assert.deepEqual(world.herdr, []);
		});
	}
});

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
			world.gh = GITHUB_PR;
			const branch = squashed();
			const result = await sweepWorktrees();
			assert.deepEqual(result.candidates.map((w: Json) => w.path), [branch.path]);
			assert.deepEqual(result.kept, []);
			assert.deepEqual(world.ghCalls, ["pr list --state merged --head feat/squashed --json number"]);
		});
	}

	for (const remote of [undefined, "https://example.com/github.com/owner/repo", "https://notgithub.com/owner/repo"]) {
		test(`other remote ${remote} never calls gh and the branch is kept unmerged`, async () => {
			world.remote = remote;
			world.gh = GITHUB_PR;
			squashed();
			const result = await sweepWorktrees();
			assert.deepEqual(result.candidates, []);
			assert.deepEqual(result.kept.map((w: Json) => w.reason), ["branch is not merged into main"]);
			assert.deepEqual(world.ghCalls, []);
		});
	}

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
	test("closes the safe orphan and notifies for it and for the others", async () => {
		setEnv();
		world.panes = [pane("w1:p2", "w1:t2", recent()), pane("w1:p3", "w1:t3", recent({ status: "working" }))];
		addState("w1:p2");
		addState("w1:p3");
		const ext = await load();
		await start(ext);
		assert.deepEqual(world.herdr, ["pane current --current", "pane list", "tab close w1:t2", "pane list"]);
		assert.deepEqual(notices(ext).map(([text, level]) => [level, text.includes("w1:p2"), text.includes("w1:p3")]), [["info", true, false], ["warning", false, true]]);
	});

	for (const [label, env, config] of [
		["in a delegated agent", { PI_HERDSMAN_MAILBOX: "/mailbox" }, undefined],
		["in a subagent", { PI_SUBAGENT_CHILD: "1" }, undefined],
		["outside Herdr", { HERDR_ENV: undefined }, undefined],
		["when disabled", {}, '{"enabled": false}'],
	] as const) {
		test(`does not sweep ${label}`, async () => {
			setEnv(env);
			if (config) memory.write(join(root, "agent/pane-reaper.json"), config);
			world.panes = [pane("w1:p2", "w1:t2", recent())];
			addState("w1:p2");
			await start(await load());
			assert.deepEqual(world.herdr, []);
		});
	}

	test("outside Herdr warns once", async () => {
		setEnv({ HERDR_ENV: undefined });
		const ext = await load();
		await start(ext, 2);
		assert.deepEqual(notices(ext).map(([text, level]) => [level, /herdr/i.test(text)]), [["warning", true]]);
	});

	test("a flagged pane is mentioned once across sessions", async () => {
		setEnv();
		world.panes = [pane("w1:p3", "w1:t3", recent({ status: "working" }))];
		addState("w1:p3");
		const ext = await load();
		await start(ext, 2);
		assert.equal(notices(ext).length, 1);
	});

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
	test("check now reports flagged panes, says when there are none and closes the safe orphan", async () => {
		world.panes = [pane("w1:p3", "w1:t3", recent({ status: "working" }))];
		addState("w1:p3");
		const ext = await load();
		const first = await command(ext, "", "");
		assert.deepEqual(first.map(([, level]) => level), ["warning", "warning"]);
		assert.match(first[0][0], /\/pane-reaper close w1:p3/);
		world.panes = [];
		assert.deepEqual(await command(ext, ""), [["pane-reaper: no orphaned panes", "info"]]);
		world.panes = [pane("w1:p2", "w1:t2", recent())];
		addState("w1:p2");
		assert.deepEqual((await command(ext, "")).map(([, level]) => level), ["info"]);
		assert.equal(world.herdr.at(-2), "tab close w1:t2");
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

	test("close closes a flagged pane and refuses any other", async () => {
		world.panes = [pane("w1:p3", "w1:t3", recent({ status: "working" })), pane("w1:p4", "w1:t4", recent({ managed: false })), pane("w1:p5", "w1:t5", { status: "working", started: Date.now() - 5 * MINUTE_MS })];
		addState("w1:p3");
		addState("w1:p5");
		const result = await command(await load(), "close w1:p4", "close w1:p5", "close w1:p3", "close", "bogus");
		assert.deepEqual(result.map(([, level]) => level), ["warning", "warning", "info", "warning", "warning"]);
		assert.deepEqual(world.herdr.filter((call) => call.includes("close")), ["tab close w1:t3"]);
	});

	test("on and off rewrite the config keeping other keys", async () => {
		const file = join(root, "agent/pane-reaper.json");
		memory.write(file, '{"graceSeconds": 60}');
		const ext = await load();
		await command(ext, "off");
		assert.deepEqual(JSON.parse(memory.read(file)), { graceSeconds: 60, enabled: false });
		await command(ext, "on");
		assert.deepEqual(JSON.parse(memory.read(file)), { graceSeconds: 60, enabled: true });
	});
});

test("config interval is clamped", async () => {
	const { readConfig } = (await load()).module;
	const file = join(root, "pane-reaper.json");
	memory.write(file, JSON.stringify({ enabled: false, graceSeconds: 30, intervalSeconds: 1 }));
	assert.deepEqual(readConfig(file), { enabled: false, graceSeconds: 30, intervalSeconds: 10 });
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
	const result = await (await load()).module.sweepOrphans({ selfPids: [9000], uid: 501, workspaceId: WORKSPACE }, false, deps);
	assert.deepEqual(result.killed.map((killed: Json) => killed.proc.pid), [445]);
});
