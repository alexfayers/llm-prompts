import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const LSP_EXTENSION = "pi-lsp-extension";

const RESOURCE_KEYS = ["packages", "extensions", "skills", "prompts", "themes"];
const sourceOf = (entry: unknown): string => (typeof entry === "string" ? entry : ((entry as { source?: string } | null)?.source ?? ""));
const isRelative = (source: string) => !path.isAbsolute(source) && !source.startsWith("~") && !/^[a-z][a-z0-9+.-]*:/i.test(source);

/** Resolves a plain relative resource path against `agentDir`, the base pi would use for the original settings file. Override and glob patterns stay as written, since pi matches them against the files of the settings directory. */
const absolute = (agentDir: string, entry: unknown): unknown => {
	const source = sourceOf(entry);
	if (!isRelative(source) || /^[!+-]|[*?]/.test(source)) return entry;
	const resolved = path.resolve(agentDir, source);
	return typeof entry === "string" ? resolved : { ...(entry as object), source: resolved };
};

export type ReadOnlyAgentDir = { dir: string };

const LOCK_STALE_MS = 10_000;
const LOCK_RETRY_MS = 20;

/** Runs `build` while holding `lock`, a directory only one fork can create. Waits for the holder, and breaks a lock older than `LOCK_STALE_MS` that a stopped fork left behind. */
function withLock<T>(lock: string, build: () => T): T {
	for (;;) {
		try {
			fs.mkdirSync(lock);
			break;
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
			const held = fs.lstatSync(lock, { throwIfNoEntry: false });
			if (held && Date.now() - held.mtimeMs > LOCK_STALE_MS) fs.rmSync(lock, { recursive: true, force: true });
			else Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, LOCK_RETRY_MS);
		}
	}
	try {
		return build();
	} finally {
		fs.rmSync(lock, { recursive: true, force: true });
	}
}
const uid = process.getuid?.();
const ownedDirectory = (target: string) => {
	const stat = fs.lstatSync(target, { throwIfNoEntry: false });
	return Boolean(stat?.isDirectory() && stat.uid === uid);
};

/** A directory only this user can use, so no other user can plant entries there. Refuses a symlink, a directory of another user, or one open to group or others. */
function privateRoot(tempRoot: string): string {
	const root = path.join(tempRoot, `pi-context-agent-${uid}`);
	fs.mkdirSync(root, { recursive: true, mode: 0o700 });
	if (!ownedDirectory(root) || (fs.lstatSync(root).mode & 0o077) !== 0) throw new Error(`${root} is not a private directory of this user`);
	return root;
}

/** Whether `dir` holds exactly the settings and links built for these inputs. */
const isBuilt = (dir: string, json: string, links: Map<string, string>): boolean => {
	try {
		if (!ownedDirectory(dir)) return false;
		const settings = path.join(dir, "settings.json");
		if (!fs.lstatSync(settings).isFile() || fs.readFileSync(settings, "utf8") !== json) return false;
		const entries = fs.readdirSync(dir).filter((name) => name !== "settings.json");
		return entries.length === links.size && entries.every((name) => links.get(name) === fs.readlinkSync(path.join(dir, name)));
	} catch {
		return false;
	}
};

/** Makes a directory in a private root under `tempRoot` that links each entry of `agentDir` except settings.json and holds settings that leave out the language server extension, so a read-only delegate started with it as its agent directory starts no language server. The name comes from a hash of the agent directory, its entries and those settings, so forks with the same inputs share one directory and one prompt cache prefix. The directory is built aside and renamed into place under a per-directory lock, checked before each reuse, and stays for later forks. */
export function readOnlyAgentDir(agentDir: string, tempRoot = os.tmpdir()): ReadOnlyAgentDir {
	const names = fs.readdirSync(agentDir).filter((name) => name !== "settings.json");
	let settings: Record<string, unknown> = {};
	try { settings = JSON.parse(fs.readFileSync(path.join(agentDir, "settings.json"), "utf8")); } catch { /* no settings to copy */ }
	for (const key of RESOURCE_KEYS) {
		if (!Array.isArray(settings[key])) continue;
		const kept = ["packages", "extensions"].includes(key) ? settings[key].filter((entry) => !sourceOf(entry).includes(LSP_EXTENSION)) : settings[key];
		settings[key] = kept.map((entry: unknown) => absolute(agentDir, entry));
	}
	const json = JSON.stringify(settings);
	const links = new Map(names.map((name) => [name, path.join(agentDir, name)]));
	const hash = createHash("sha256").update(JSON.stringify([agentDir, names, json])).digest("hex").slice(0, 12);
	const root = privateRoot(tempRoot);
	const dir = path.join(root, hash);
	if (isBuilt(dir, json, links)) return { dir };
	withLock(`${dir}.lock`, () => {
		if (isBuilt(dir, json, links)) return;
		fs.rmSync(dir, { recursive: true, force: true });
		const staging = fs.mkdtempSync(path.join(root, "staging-"));
		try {
			for (const [name, target] of links) fs.symlinkSync(target, path.join(staging, name));
			fs.writeFileSync(path.join(staging, "settings.json"), json, { mode: 0o600 });
			fs.renameSync(staging, dir);
		} catch (error) {
			fs.rmSync(staging, { recursive: true, force: true });
			throw error;
		}
	});
	return { dir };
}
