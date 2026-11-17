// A synthetic repository with a remote, saved ghosts for it, and a session extension with a push guard, shared by the ghost session tests.
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { VERSION } from "@earendil-works/pi-coding-agent";
import { type Check, type Ghost, type Step, stepsHash } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/ghost/model.ts";
import { repoKey } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/merge.ts";
import { registerGhostRun } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/ghost/run.ts";
import { ghostPath, writeGhost } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/ghost/store.ts";

export const PUSH_REASON = 'Blocked by guard: DENIED "no pushing to remote"';

const git = (cwd: string, ...args: string[]) => execFileSync("git", ["-c", "user.name=t", "-c", "user.email=t@example.com", ...args], { cwd, stdio: "pipe", encoding: "utf8" });
const bash = (command: string, check: Check): Step => ({ tool: "bash", args: { command }, check, isError: false });
const match = (regex: string): Check => ({ isError: false, output: { regex } });
const SILENT: Check = { isError: false, output: { regex: "^(\\(no output\\))?$" } };

/** A clone whose origin is one commit ahead, with ghosts that sync it and push it. */
export async function makeFixture() {
	const root = mkdtempSync(join(tmpdir(), "ghost-session-"));
	const [origin, seed, work] = ["origin.git", "seed", "work"].map((name) => join(root, name));
	git(root, "init", "--bare", "-b", "main", origin);
	git(root, "clone", origin, seed);
	writeFileSync(join(seed, "a.txt"), "one\n");
	git(seed, "add", "a.txt");
	git(seed, "commit", "-m", "first");
	git(seed, "push", "origin", "HEAD:main");
	git(root, "clone", origin, work);
	writeFileSync(join(seed, "a.txt"), "two\n");
	git(seed, "commit", "-am", "second");
	git(seed, "push", "origin", "HEAD:main");

	const save = async (name: string, steps: Step[]) => {
		const ghost: Ghost = { version: 1, name, repoKey: repoKey(work), branch: "main", piVersion: VERSION, params: {}, steps, approvedHash: stepsHash(steps) };
		await writeGhost(ghostPath(ghost.repoKey, name), ghost);
	};
	await save("sync-main", [
		bash("git fetch --quiet origin", SILENT),
		bash("git status --porcelain", SILENT),
		bash("git merge --ff-only origin/main", match("Fast-forward|up to date")),
		bash("git log -1 --format=%s", match("^second$")),
	]);
	await save("push-main", [bash("git push origin main", SILENT)]);
	return {
		work,
		origin,
		head: () => git(work, "log", "-1", "--format=%s").trim(),
		dirty: () => writeFileSync(join(work, "a.txt"), "local edit\n"),
		cleanup: () => rmSync(root, { recursive: true }),
	};
}

export interface Seen {
	/** Every tool call as `tool` or `tool<-parent`, in order. */
	calls: string[];
}

/** The ghost_run tool plus a guard that blocks `git push`, recording each tool call. */
export const sessionExtension = (seen: Seen) => (pi: ExtensionAPI) => {
	registerGhostRun(pi);
	pi.on("tool_call", (event) => {
		seen.calls.push(event.parentToolCallId ? `${event.toolName}<-${event.parentToolCallId.split("/")[0]}` : event.toolName);
		if (event.toolName === "bash" && /git push/.test(String((event.input as { command?: string }).command))) return { block: true, reason: PUSH_REASON };
	});
};

/** The text of every ghost_run result in the session, in order. */
export const ghostResults = (entries: any[]) =>
	entries.filter((entry) => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "ghost_run").map((entry) => ({ text: entry.message.content.map((part: any) => part.text).join(""), isError: entry.message.isError as boolean }));
