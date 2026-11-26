import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, describe, test } from "node:test";
import { type Event, type WorktreeProvider, WORKTREE_PROVIDER, createWorktree, land, restoreWorktree, resumeWorktree } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/merge.ts";

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-merge-"));
after(() => fs.rmSync(scratch, { recursive: true }));

const git = (cwd: string, ...args: string[]) => execFileSync("git", ["-c", "user.name=t", "-c", "user.email=t@example.com", ...args], { cwd, encoding: "utf8", stdio: "pipe" }).trim();
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

describe("landing", () => {
	test("a fork that stops without landing loses its worktree only when it left nothing in it, and a resume brings it back", async () => {
		const repo = newRepo();
		const [clean, worked] = [await writer(repo, "clean"), await writer(repo, "worked")];
		commit(worked.path, "worked.txt", "1");
		const blocked: Event = { type: "fork-blocked", reason: "needs input" };
		assert.deepEqual(await land({ tree: clean, first: blocked }), { state: "escalated", reason: "fork is blocked: needs input", removed: true });
		assert.equal((await land({ tree: worked, first: blocked })).removed, false);
		assert.ok(!fs.existsSync(clean.path));
		await restoreWorktree(clean);
		assert.equal(git(clean.path, "symbolic-ref", "--short", "HEAD"), "fork/clean");
	});

	test("a cancelled fork lands nothing and keeps its commits", async () => {
		const repo = newRepo();
		const tree = await writer(repo, "cancelled");
		commit(tree.path, "a.txt", "1", "work");
		const before = git(repo, "rev-parse", "HEAD");
		const landing = await land({ tree, first: done, signal: AbortSignal.abort() });
		assert.deepEqual([landing.state, landing.reason, landing.removed], ["escalated", "cancelled before landing", false]);
		assert.equal(git(repo, "rev-parse", "HEAD"), before);
		assert.ok(fs.existsSync(tree.path));
	});

	test("with rebase, parallel writers on one base each land after rebasing onto the branch the others advanced, and a conflicting one is left as it was", async () => {
		const repo = newRepo();
		const [first, second, clash] = [await writer(repo, "first"), await writer(repo, "second"), await writer(repo, "clash")];
		commit(first.path, "a.txt", "1", "first work");
		commit(second.path, "b.txt", "2", "second work");
		commit(clash.path, "a.txt", "3", "clash work");
		const landings = await Promise.all([first, second, clash].map((tree) => land({ tree, first: done, rebase: true })));
		assert.deepEqual(landings.map((landing) => landing.state), ["landed", "landed", "escalated"]);
		assert.deepEqual(subjects(repo, "HEAD~2..HEAD"), ["second work", "first work"]);
		assert.match(landings[2].reason ?? "", /do not sit on the current main/);
		assert.equal(git(clash.path, "status", "--porcelain"), "");
		assert.deepEqual(subjects(clash.path, "HEAD~1..HEAD"), ["clash work"]);
		const loose = await writer(repo, "loose");
		commit(loose.path, "c.txt", "4", "loose work");
		commit(repo, "d.txt", "5", "lead moved");
		assert.match((await land({ tree: loose, first: done })).reason ?? "", /do not sit on the current main/);
	});

	test("with rebase, a writer started from a commit the lead then amended is not replayed over the amend", async () => {
		const repo = newRepo();
		commit(repo, "x.txt", "1", "lead x");
		const tree = await writer(repo, "stale");
		commit(tree.path, "a.txt", "1", "stale work");
		git(repo, "rm", "-q", "x.txt");
		git(repo, "commit", "-q", "--amend", "--allow-empty", "-m", "lead without x");
		const landing = await land({ tree, first: done, rebase: true });
		assert.equal(landing.state, "escalated");
		assert.match(landing.reason ?? "", /do not sit on the current main/);
		assert.equal(fs.existsSync(path.join(repo, "x.txt")), false);
		assert.deepEqual(subjects(tree.path, "HEAD~1..HEAD"), ["stale work"]);
	});

	test("rewritten commits on the current base fast-forward the main checkout", async () => {
		const repo = newRepo();
		const tree = await writer(repo, "rewrite");
		commit(tree.path, "a.txt", "1", "first");
		commit(tree.path, "a.txt", "2", "second");
		git(tree.path, "reset", "--soft", "HEAD~2");
		git(tree.path, "commit", "-m", "squashed");
		const landing = await land({ tree, first: done });
		assert.equal(landing.state, "landed");
		assert.equal(landing.sha, git(repo, "rev-parse", "HEAD"));
		assert.deepEqual(subjects(repo, "HEAD~1..HEAD"), ["squashed"]);
		assert.ok(!fs.existsSync(tree.path));
	});

	test("a fork that rebased the base's commits onto a newer origin/main lands on its tip", async () => {
		const repo = newRepo();
		git(repo, "update-ref", "refs/remotes/origin/main", "HEAD");
		commit(repo, "lead.txt", "1", "lead");
		const tree = await writer(repo, "rebased");
		git(tree.path, "reset", "-q", "--hard", "origin/main");
		commit(tree.path, "up.txt", "1", "upstream");
		git(tree.path, "update-ref", "refs/remotes/origin/main", "HEAD");
		git(tree.path, "cherry-pick", "main");
		commit(tree.path, "a.txt", "1", "fork work");
		const landing = await land({ tree, first: done });
		assert.deepEqual([landing.state, landing.reason], ["landed", undefined]);
		assert.deepEqual(subjects(repo, "HEAD~3..HEAD"), ["fork work", "lead", "upstream"]);
		assert.equal(git(repo, "status", "--porcelain"), "");
	});

	test("a fork that folded a fixup into a commit of a PR branch behind origin/main lands on that branch", async () => {
		const repo = newRepo();
		git(repo, "update-ref", "refs/remotes/origin/main", "HEAD");
		const pr = path.join(scratch, "pr-worktree");
		git(repo, "worktree", "add", "-q", "-b", "feat/pr", pr);
		commit(pr, "pr.txt", "1", "pr work");
		commit(repo, "up.txt", "1", "upstream");
		git(repo, "update-ref", "refs/remotes/origin/main", "HEAD");
		const tree = await writer(pr, "fold-pr");
		commit(tree.path, "pr.txt", "2", "fixup! pr work");
		execFileSync("git", ["rebase", "-q", "-i", "--autosquash", "HEAD~2"], { cwd: tree.path, env: { ...process.env, GIT_SEQUENCE_EDITOR: "true" } });
		const landing = await land({ tree, first: done });
		assert.deepEqual([landing.state, landing.reason], ["landed", undefined]);
		assert.equal(git(pr, "symbolic-ref", "--short", "HEAD"), "feat/pr");
		assert.deepEqual(subjects(pr, "origin/main..HEAD"), ["pr work"]);
		assert.equal(git(pr, "show", "HEAD:pr.txt"), "2");
	});

	test("a fork that rebased away a merge commit of a PR branch escalates", async () => {
		const repo = newRepo();
		git(repo, "update-ref", "refs/remotes/origin/main", "HEAD");
		const pr = path.join(scratch, "pr-merged");
		git(repo, "worktree", "add", "-q", "-b", "feat/merged", pr);
		commit(pr, "pr.txt", "1", "pr work");
		commit(repo, "up.txt", "1", "upstream");
		git(repo, "update-ref", "refs/remotes/origin/main", "HEAD");
		git(pr, "merge", "-q", "--no-ff", "-m", "merge main", "origin/main");
		const tree = await writer(pr, "flatten");
		commit(tree.path, "pr.txt", "2", "fixup! pr work");
		execFileSync("git", ["rebase", "-q", "-i", "--autosquash", "origin/main"], { cwd: tree.path, env: { ...process.env, GIT_SEQUENCE_EDITOR: "true" } });
		assert.match((await land({ tree, first: done })).reason ?? "", /do not sit on the current feat\/merged/);
	});

	test("a fork on a newer origin/main that dropped a base commit escalates", async () => {
		const repo = newRepo();
		git(repo, "update-ref", "refs/remotes/origin/main", "HEAD");
		commit(repo, "lead.txt", "1", "lead");
		const tree = await writer(repo, "dropped");
		git(tree.path, "reset", "-q", "--hard", "origin/main");
		commit(tree.path, "up.txt", "1", "upstream");
		git(tree.path, "update-ref", "refs/remotes/origin/main", "HEAD");
		commit(tree.path, "a.txt", "1", "fork work");
		assert.match((await land({ tree, first: done })).reason ?? "", /do not sit on the current main/);
	});

	test("a fork on a newer origin/main that folded a fixup into a base commit lands, but another commit with its subject does not stand in for it", async () => {
		for (const [name, file, landed] of [["folded", "lead.txt", true], ["impostor", "other.txt", false]] as const) {
			const repo = newRepo();
			git(repo, "update-ref", "refs/remotes/origin/main", "HEAD");
			commit(repo, "lead.txt", "1", "lead");
			const tree = await writer(repo, name);
			git(tree.path, "reset", "-q", "--hard", "origin/main");
			commit(tree.path, "up.txt", "1", "upstream");
			git(tree.path, "update-ref", "refs/remotes/origin/main", "HEAD");
			commit(tree.path, file, "2", "lead");
			const landing = await land({ tree, first: done });
			assert.equal(landing.state === "landed", landed, `${name}: ${landing.reason}`);
		}
	});

	describe("a writer that starts its own branch from a base ref", () => {
		function originRepo(name: string) {
			const repo = newRepo();
			const remote = path.join(scratch, `${name}.git`);
			git(scratch, "init", "-q", "--bare", remote);
			git(repo, "remote", "add", "origin", remote);
			git(repo, "push", "-q", "origin", "main");
			git(repo, "fetch", "-q", "origin");
			commit(repo, "local.txt", "1", "local only");
			return repo;
		}
		const own = (repo: string, name: string) => createWorktree(repo, path.join(scratch, "worktrees"), name, { base: "origin/main", branch: "feature/own" });

		test("starts on the named branch from the base, not the current branch", async () => {
			const repo = originRepo("start");
			const tree = await own(repo, "own-start");
			assert.equal(tree.branch, "feature/own");
			assert.equal(git(tree.path, "symbolic-ref", "--short", "HEAD"), "feature/own");
			assert.equal(git(tree.path, "rev-parse", "HEAD"), git(repo, "rev-parse", "origin/main"));
		});

		test("lands by the branch push without escalating", async () => {
			const repo = originRepo("pushed");
			const tree = await own(repo, "own-pushed");
			commit(tree.path, "a.txt", "1", "pr work");
			git(tree.path, "push", "-q", "origin", "HEAD");
			const before = git(repo, "rev-parse", "HEAD");
			const landing = await land({ tree, first: done });
			assert.equal(landing.state, "landed");
			assert.match(landing.note ?? "", /landed on origin\/feature\/own by push/);
			assert.equal(git(repo, "rev-parse", "HEAD"), before);
		});

		test("escalates and keeps the work when the branch was not pushed", async () => {
			const repo = originRepo("unpushed");
			const tree = await own(repo, "own-unpushed");
			commit(tree.path, "a.txt", "1", "pr work");
			const before = git(repo, "rev-parse", "HEAD");
			const landing = await land({ tree, first: done });
			assert.equal(landing.state, "escalated");
			assert.match(landing.reason ?? "", /feature\/own was not pushed/);
			assert.equal(git(repo, "rev-parse", "HEAD"), before);
			assert.ok(fs.existsSync(tree.path));
		});

		test("pushes with a plain git push", async () => {
			const repo = originRepo("plain");
			const tree = await own(repo, "own-plain");
			commit(tree.path, "a.txt", "1", "pr work");
			git(tree.path, "-c", "push.default=simple", "push", "-q");
			assert.equal(git(repo, "rev-parse", "origin/feature/own"), git(tree.path, "rev-parse", "HEAD"));
		});

		test("fetches the base and refuses a branch that exists on origin", async () => {
			const repo = originRepo("fetch");
			const other = path.join(scratch, "fetch-other");
			git(scratch, "clone", "-q", "-b", "main", path.join(scratch, "fetch.git"), other);
			commit(other, "up.txt", "1", "upstream moved");
			git(other, "push", "-q", "origin", "HEAD:main");
			const tree = await own(repo, "own-fetch");
			assert.equal(git(tree.path, "rev-parse", "HEAD"), git(other, "rev-parse", "HEAD"));
			git(other, "push", "-q", "origin", "HEAD:feature/taken");
			await assert.rejects(createWorktree(repo, path.join(scratch, "worktrees"), "own-taken", { base: "origin/main", branch: "feature/taken" }), /feature\/taken/);
		});

		test("a restored worktree continues from the pushed branch", async () => {
			const repo = originRepo("restore");
			const tree = await own(repo, "own-restore");
			commit(tree.path, "a.txt", "1", "pr work");
			git(tree.path, "push", "-q");
			assert.equal((await land({ tree, first: done })).state, "landed");
			await restoreWorktree(tree);
			assert.equal(git(tree.path, "rev-parse", "HEAD"), git(repo, "rev-parse", "origin/feature/own"));
		});

		test("a continued run resumes on the pushed branch and pushes again as a fast-forward", async () => {
			const repo = originRepo("resume");
			const root = path.join(scratch, "worktrees");
			const first = await own(repo, "own-resume");
			commit(first.path, "a.txt", "1", "first round");
			git(first.path, "push", "-q");
			assert.equal((await land({ tree: first, first: done })).state, "landed");
			assert.ok(!fs.existsSync(first.path));
			const tree = await resumeWorktree(first, root, "own-resume");
			assert.equal(git(tree.path, "rev-parse", "HEAD"), git(repo, "rev-parse", "origin/feature/own"));
			commit(tree.path, "b.txt", "1", "fix round");
			git(tree.path, "push", "-q");
			assert.equal(git(repo, "rev-parse", "origin/feature/own"), git(tree.path, "rev-parse", "HEAD"));
			assert.equal((await land({ tree, first: done })).state, "landed");
		});

		test("a continued run keeps the unpushed commits of a kept worktree", async () => {
			const repo = originRepo("kept");
			const first = await own(repo, "own-kept");
			commit(first.path, "a.txt", "1", "unpushed");
			assert.equal((await land({ tree: first, first: done })).state, "escalated");
			const tree = await resumeWorktree(first, path.join(scratch, "worktrees"), "own-kept");
			assert.equal(tree.path, first.path);
			assert.equal(git(tree.path, "log", "-1", "--format=%s"), "unpushed");
		});

		test("a worktree restored on a new branch pushes with a plain git push", async () => {
			const repo = originRepo("restore-new");
			const tree = await own(repo, "own-restore-new");
			assert.equal((await land({ tree, first: { type: "fork-blocked", reason: "needs input" } })).removed, true);
			await restoreWorktree(tree);
			commit(tree.path, "a.txt", "1", "pr work");
			git(tree.path, "-c", "push.default=simple", "push", "-q");
			assert.equal(git(repo, "rev-parse", "origin/feature/own"), git(tree.path, "rev-parse", "HEAD"));
		});

		test("rejects a base without a branch", async () => {
			await assert.rejects(createWorktree(originRepo("nobranch"), path.join(scratch, "worktrees"), "own-nobranch", { base: "origin/main" }), /branch/);
		});
	});

	describe("a fork whose commits were pushed to another remote branch", () => {
		let remoteCount = 0;
		async function pushedFork(name: string) {
			const repo = newRepo();
			const remote = path.join(scratch, `remote${remoteCount++}.git`);
			git(scratch, "init", "-q", "--bare", remote);
			git(repo, "remote", "add", "origin", remote);
			git(repo, "push", "-q", "origin", "main");
			const tree = await writer(repo, name);
			commit(tree.path, "a.txt", "1", "pushed work");
			git(tree.path, "push", "-q", "origin", "HEAD:pr-branch");
			commit(repo, "b.txt", "main moved");
			return { repo, remote, tree };
		}

		test("lands there, not on its base", async () => {
			const { repo, tree } = await pushedFork("pushed");
			const before = git(repo, "rev-parse", "HEAD");
			const landing = await land({ tree, first: done });
			assert.equal(landing.state, "landed");
			assert.match(landing.note ?? "", /landed on origin\/pr-branch by push/);
			assert.equal(git(repo, "rev-parse", "HEAD"), before);
			assert.ok(!fs.existsSync(tree.path));
			assert.equal(git(repo, "branch", "--list", tree.branch), "");
		});

		test("escalates when the remote branch is gone or the fetch fails, and keeps the work", async () => {
			const gone = await pushedFork("gone");
			git(gone.remote, "branch", "-q", "-D", "pr-branch");
			const unreachable = await pushedFork("unreachable");
			git(unreachable.repo, "remote", "set-url", "origin", path.join(scratch, "missing.git"));
			for (const { repo, tree } of [gone, unreachable]) {
				const landing = await land({ tree, first: done });
				assert.equal(landing.state, "escalated", tree.branch);
				assert.match(landing.reason ?? "", /do not sit on the current main/, tree.branch);
				assert.ok(fs.existsSync(tree.path), tree.branch);
				assert.notEqual(git(repo, "branch", "--list", tree.branch), "", tree.branch);
			}
		});

		test("escalates when only a remote that was not fetched holds a stale ref", async () => {
			const { repo, remote, tree } = await pushedFork("stale-remote");
			const stale = path.join(scratch, "stale.git");
			git(scratch, "init", "-q", "--bare", stale);
			git(repo, "remote", "add", "stale", stale);
			git(tree.path, "push", "-q", "stale", "HEAD:pr-branch");
			git(remote, "branch", "-q", "-D", "pr-branch");
			const landing = await land({ tree, first: done });
			assert.equal(landing.state, "escalated");
			assert.ok(fs.existsSync(tree.path));
			assert.notEqual(git(repo, "branch", "--list", tree.branch), "");
		});

		describe("escalating after the push", () => {
			const escalated = async (name: string, setup: (tree: Awaited<ReturnType<typeof writer>>, repo: string) => void) => {
				const { repo, tree } = await pushedFork(name);
				setup(tree, repo);
				return { repo, tree, landing: await land({ tree, first: done }) };
			};
			const notes = (tree: { path: string }) => (fs.mkdirSync(path.join(tree.path, ".context")), fs.writeFileSync(path.join(tree.path, ".context", "notes.md"), "x"));

			test("removes the worktree and branch when only untracked .context files remain", async () => {
				const { repo, tree, landing } = await escalated("context-only", notes);
				assert.equal(landing.state, "escalated");
				assert.equal(landing.removed, true);
				assert.ok(!fs.existsSync(tree.path));
				assert.equal(git(repo, "branch", "--list", tree.branch), "");
			});

			test("removes them when origin/main holds the same patches", async () => {
				const { repo, tree, landing } = await escalated("on-main", (tree, repo) => {
					git(tree.path, "push", "-q", "origin", "--delete", "pr-branch");
					git(repo, "cherry-pick", tree.branch);
					git(repo, "push", "-q", "origin", "main");
					notes(tree);
				});
				assert.equal(landing.removed, true);
				assert.ok(!fs.existsSync(tree.path));
				assert.equal(git(repo, "branch", "--list", tree.branch), "");
			});

			test("keeps them when a tracked file changed, another file is untracked, or a commit is not pushed", async () => {
				const cases: [string, (tree: Awaited<ReturnType<typeof writer>>) => void][] = [
					["tracked", (tree) => (notes(tree), fs.writeFileSync(path.join(tree.path, "a.txt"), "changed"))],
					["untracked", (tree) => (notes(tree), fs.writeFileSync(path.join(tree.path, "loose.txt"), "x"))],
					["unpushed", (tree) => (notes(tree), commit(tree.path, "c.txt", "1", "unpushed work"))],
				];
				for (const [name, setup] of cases) {
					const { repo, tree, landing } = await escalated(`keep-${name}`, setup);
					assert.equal(landing.state, "escalated", name);
					assert.equal(landing.removed, false, name);
					assert.ok(fs.existsSync(tree.path), name);
					assert.notEqual(git(repo, "branch", "--list", tree.branch), "", name);
				}
			});
		});

		test("escalates when the worktree left the fork branch for a pushed one", async () => {
			const { repo, tree } = await pushedFork("switched");
			git(tree.path, "switch", "-q", "-c", "other", "main");
			commit(tree.path, "c.txt", "1", "other work");
			git(tree.path, "push", "-q", "origin", "HEAD:other-pr");
			git(tree.path, "push", "-q", "origin", "--delete", "pr-branch");
			const landing = await land({ tree, first: done });
			assert.equal(landing.state, "escalated");
			assert.match(landing.reason ?? "", /left fork\/switched/);
			assert.ok(fs.existsSync(tree.path));
			assert.notEqual(git(repo, "branch", "--list", tree.branch), "");
		});
	});

	test("a fork with no commits lands as a no-op and drops its worktree", async () => {
		const repo = newRepo();
		const tree = await writer(repo, "empty");
		assert.deepEqual(await land({ tree, first: done }), { state: "landed", note: undefined });
		assert.ok(!fs.existsSync(tree.path));
	});

	test("commits that cannot land escalate and keep the worktree", async () => {
		const cases: [string, (tree: Awaited<ReturnType<typeof writer>>, repo: string) => void, RegExp][] = [
			["dirty", (tree) => fs.writeFileSync(path.join(tree.path, "loose.txt"), "x"), /uncommitted changes/],
			["fixup", (tree) => commit(tree.path, "a.txt", "1", "fixup! edit shared.txt"), /fixup!/],
			["private", (tree) => commit(tree.path, "a.txt", "token secret-42"), /private/],
			["home", (tree) => commit(tree.path, "a.txt", `${os.homedir()}/notes`), /private/],
			["off-branch", (tree) => (commit(tree.path, "a.txt", "1"), git(tree.path, "switch", "-q", "--detach")), /left fork\/off-branch/],
			["stale base", (tree, repo) => (commit(tree.path, "a.txt", "1"), commit(repo, "b.txt", "main moved")), /do not sit on the current main/],
			["main dirty", (tree, repo) => (commit(tree.path, "a.txt", "1"), fs.writeFileSync(path.join(repo, "loose.txt"), "x")), /main checkout changed/],
		];
		for (const [name, setup, reason] of cases) {
			const repo = newRepo();
			const tree = await writer(repo, name.replace(" ", "-"));
			setup(tree, repo);
			const landing = await land({ tree, first: done, privateNames: "secret-[0-9]+" });
			assert.equal(landing.state, "escalated", name);
			assert.match(landing.reason ?? "", reason, name);
			assert.ok(fs.existsSync(tree.path), name);
		}
	});

	test("a failed fork escalates", async () => {
		const repo = newRepo();
		const tree = await writer(repo, "failed");
		assert.equal((await land({ tree, first: { type: "fork-failed", reason: "boom" } })).reason, "fork failed: boom");
	});
});

describe("worktree provider", () => {
	const registered = globalThis as { [WORKTREE_PROVIDER]?: WorktreeProvider };
	after(() => delete registered[WORKTREE_PROVIDER]);
	const removed: string[] = [];
	/** Clones the target into a git checkout nested in a bigger directory, or declines a target named in `declined`. */
	const clones = (declined = ""): WorktreeProvider => ({
		create: async (target, branch, base) => {
			if (target === declined) return undefined;
			const dir = path.join(scratch, "provided", path.basename(target));
			git(scratch, "clone", "-q", "-b", base, target, path.join(dir, "src", "checkout"));
			git(path.join(dir, "src", "checkout"), "switch", "-q", "-c", branch);
			return { path: dir, gitDir: path.join(dir, "src", "checkout") };
		},
		remove: async (dir) => void (removed.push(dir), fs.rmSync(dir, { recursive: true })),
	});

	test("makes the worktree, lands its commits from the nested checkout and removes it", async () => {
		const repo = newRepo();
		registered[WORKTREE_PROVIDER] = clones();
		const tree = await writer(repo, "provided");
		assert.equal(tree.path, path.join(scratch, "provided", path.basename(repo)));
		commit(tree.checkout!, "a.txt", "1", "from the provider");
		const landing = await land({ tree, first: done });
		assert.equal(landing.state, "landed");
		assert.deepEqual(subjects(repo, "HEAD~1..HEAD"), ["from the provider"]);
		assert.deepEqual(removed, [tree.path]);
		assert.ok(!fs.existsSync(tree.path));
	});

	test("a declined target gets a git worktree", async () => {
		const repo = newRepo();
		registered[WORKTREE_PROVIDER] = clones(repo);
		const tree = await writer(repo, "declined");
		assert.equal(tree.provided, undefined);
		assert.equal(git(tree.path, "symbolic-ref", "--short", "HEAD"), "fork/declined");
	});
});
