// Preserves complete fork transcripts outside usage stores and writes child-only accounting sessions.
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

type Entry = { type: string; id: string; parentId?: string | null; message?: { role: string; content?: unknown }; piContextUsage?: { version: number; sourceHash: string }; piContextFork?: { inherited?: string | null; parentSessionId: string } };
const hash = (data: string | Buffer) => createHash("sha256").update(data).digest("hex");
const signature = (entry: Entry) => hash(JSON.stringify(entry));
const parse = (data: Buffer): Entry[] => {
	const entries = data.toString("utf8").trimEnd().split("\n").map((line) => JSON.parse(line) as Entry);
	if (entries[0]?.type !== "session" || !entries[0].id || entries.slice(1).some((entry) => !entry.id || entry.type === "session") || new Set(entries.slice(1).map((entry) => entry.id)).size !== entries.length - 1) throw new Error("Invalid session transcript");
	return entries;
};

function directory(dir: string): void {
	fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
	if (fs.lstatSync(dir).isSymbolicLink()) throw new Error(`Refusing symlink: ${dir}`);
}

function regular(file: string): void {
	if (!fs.lstatSync(file).isFile()) throw new Error(`Not a regular transcript: ${file}`);
}

function archiveSession(data: Buffer, agentDir: string): string {
	directory(path.join(agentDir, "pi-context"));
	const dir = path.join(agentDir, "pi-context", "kept");
	directory(dir);
	const file = path.join(dir, `${hash(data)}.jsonl`);
	const temp = path.join(dir, `${randomUUID()}.tmp`);
	try {
		const fd = fs.openSync(temp, "wx", 0o600);
		try { fs.writeFileSync(fd, data); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
		try { fs.linkSync(temp, file); } catch (error) {
			if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
			regular(file);
			if (!fs.readFileSync(file).equals(data)) throw new Error(`Archive mismatch: ${file}`);
		}
		syncDirectory(dir);
	} finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
	return file;
}

function projection(entries: Entry[], sourceHash: string, inherited?: string): string {
	const [header, ...body] = entries;
	const at = inherited === undefined ? -1 : body.findIndex((entry) => entry.id === inherited);
	if (inherited !== undefined && at < 0) throw new Error("Missing inherited entry");
	const own = body.slice(at + 1);
	const ids = new Set(own.map((entry) => entry.id));
	return [{ ...header, piContextUsage: { version: 1, sourceHash } }, ...own.map((entry) => ({ ...entry, ...(entry.parentId && !ids.has(entry.parentId) && { parentId: null }) }))].map((entry) => JSON.stringify(entry)).join("\n") + "\n";
}

function syncDirectory(dir: string): void {
	const fd = fs.openSync(dir, "r");
	try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
}

function replace(file: string, data: string): void {
	if (fs.existsSync(file)) regular(file);
	const temp = `${file}.${randomUUID()}.tmp`;
	try {
		const fd = fs.openSync(temp, "wx", 0o600);
		try { fs.writeFileSync(fd, data); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
		fs.renameSync(temp, file);
		syncDirectory(path.dirname(file));
	} finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
}

class ChangedError extends Error {}
class LockTimeoutError extends Error {}
const RETAIN_ATTEMPTS = 3;
/** Changes whenever a file is written, renamed over or removed. */
const identity = (file: string) => {
	const stat = fs.lstatSync(file, { throwIfNoEntry: false });
	return stat && [stat.dev, stat.ino, stat.size, stat.mtimeMs, stat.ctimeMs].join(":");
};

async function readStable(file: string): Promise<{ data: Buffer; entries: Entry[]; identity: string } | undefined> {
	const before = identity(file);
	if (!before) return undefined;
	try {
		const session = await readSession(file);
		if (identity(file) === before) return { ...session, identity: before };
	} catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
	throw new ChangedError(`Session changed while reading: ${file}`);
}

/** Archives a full snapshot before replacing the run's accounting session; resumed snapshots remain immutable. */
export async function retainSession(source: string, name: string, inherited: string | undefined, agentDir: string): Promise<{ archive: string; usage: string }> {
	if (path.basename(name) !== name || !name.endsWith(".jsonl")) throw new Error("Invalid accounting filename");
	regular(source);
	const data = await fs.promises.readFile(source);
	const entries = parse(data);
	const projected = projection(entries, hash(data), inherited);
	const archive = archiveSession(data, agentDir);
	const usage = path.join(agentDir, "sessions", "pi-context", name);
	for (let attempt = 1; ; attempt++) {
		try {
			const previous = await readStable(usage);
			if (previous) {
				const header = previous.entries[0];
				if (header.id !== entries[0].id) throw new Error(`Accounting filename collision: ${usage}`);
				if (!header.piContextUsage) archiveSession(previous.data, agentDir);
				else verifyArchive(header.piContextUsage.sourceHash, agentDir);
			}
			await withUsageLock(agentDir, () => {
				if (identity(usage) !== previous?.identity) throw new ChangedError(`Accounting session changed during retention: ${usage}`);
				replace(usage, projected);
			});
			return { archive, usage };
		} catch (error) {
			if (attempt >= RETAIN_ATTEMPTS || !(error instanceof ChangedError || error instanceof LockTimeoutError)) throw error;
		}
	}
}

const LOCK_WAIT_MS = 30_000;
const ignore = (codes: string[], run: () => void) => {
	try { run(); } catch (error) { if (!codes.includes((error as NodeJS.ErrnoException).code ?? "")) throw error; }
};

/** Holds `.usage-lock`, a directory installed by rename with its owner marker inside, so an empty lock directory is always abandoned. */
async function withUsageLock<T>(agentDir: string, run: () => T | Promise<T>): Promise<T> {
	directory(path.join(agentDir, "sessions"));
	directory(path.join(agentDir, "sessions", "pi-context"));
	const lock = path.join(agentDir, "sessions", "pi-context", ".usage-lock");
	const ownerName = `${process.pid}-${randomUUID()}`;
	const staged = `${lock}.${ownerName}.tmp`;
	fs.mkdirSync(staged, { mode: 0o700 });
	fs.writeFileSync(path.join(staged, ownerName), "", { flag: "wx", mode: 0o600 });
	const deadline = Date.now() + LOCK_WAIT_MS;
	try {
		for (;;) {
			try {
				fs.renameSync(staged, lock);
				break;
			} catch (error) {
				if (!["EEXIST", "ENOTEMPTY", "ENOTDIR", "EISDIR"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error;
				const stat = fs.lstatSync(lock, { throwIfNoEntry: false });
				if (stat && !stat.isDirectory()) throw new Error(`Refusing non-directory lock: ${lock}`);
				let names: string[] = [];
				ignore(["ENOENT"], () => { names = fs.readdirSync(lock); });
				if (names.length === 1 && /^\d+-[a-f0-9-]+$/.test(names[0])) {
					let dead = false;
					try { process.kill(Number(names[0].split("-")[0]), 0); } catch (error) { dead = (error as NodeJS.ErrnoException).code === "ESRCH"; }
					// Unlinking the dead owner's unique marker succeeds for one contender only. The empty directory left behind is free to replace.
					if (dead) { ignore(["ENOENT"], () => fs.unlinkSync(path.join(lock, names[0]))); continue; }
				}
				if (Date.now() >= deadline) throw new LockTimeoutError(`Timed out waiting for usage lock: ${lock}`);
				await new Promise((resolve) => setTimeout(resolve, 25));
			}
		}
	} catch (error) {
		fs.rmSync(staged, { recursive: true, force: true });
		throw error;
	}
	try { return await run(); } finally {
		fs.unlinkSync(path.join(lock, ownerName));
		ignore(["ENOENT", "ENOTEMPTY", "EEXIST"], () => fs.rmdirSync(lock));
	}
}

const WARM_PROMPTS = ["You are the delegate that the conversation above asked to fork, so do not call fork.", "You answer one side question for the user."];
const billed = (entry: Entry) => entry.type === "message" && entry.message?.role === "assistant";
const userText = (entry: Entry): string => {
	if (entry.type !== "message" || entry.message?.role !== "user") return "";
	const content = entry.message.content;
	if (typeof content === "string") return content;
	return Array.isArray(content) ? content.filter((block) => block?.type === "text" && typeof block.text === "string").map((block) => block.text).join("\n") : "";
};

/** An entry's exact hash, its lineage key and whether it carries usage, so unbilled metadata may differ only on a matching lineage. */
type Shape = { exact: string; key: string; usage: boolean };
const shape = (entry: Entry): Shape => ({ exact: signature(entry), key: JSON.stringify([entry.type, entry.message?.role, entry.parentId ?? null]), usage: billed(entry) || JSON.stringify(entry).includes('"usage":') });
type Parent = { id?: string; signatures: Map<string, Shape>; error?: string };
export type Migration = { changes: { file: string; sourceHash: string; inherited: string; archive?: string }[]; blocked: { file: string; reason: string }[] };

function sessionFiles(dir: string): string[] {
	if (!fs.existsSync(dir)) return [];
	if (fs.lstatSync(dir).isSymbolicLink()) throw new Error(`Refusing symlink: ${dir}`);
	return fs.readdirSync(dir).flatMap((name) => {
		const file = path.join(dir, name);
		const stat = fs.lstatSync(file);
		if (stat.isSymbolicLink()) throw new Error(`Refusing symlink: ${file}`);
		if (stat.isDirectory()) return name === "pi-context" || name.startsWith(".") ? [] : sessionFiles(file);
		return stat.isFile() && name.endsWith(".jsonl") ? [file] : [];
	});
}

/** Streams parent files, retaining only hashes for entry IDs present in legacy forks. */
async function parentIndex(files: string[], wanted: Set<string>): Promise<Parent[]> {
	const parents: Parent[] = [];
	for (const file of files) {
		const parent: Parent = { signatures: new Map() };
		const input = fs.createReadStream(file);
		const lines = createInterface({ input, crlfDelay: Infinity });
		input.on("error", (error) => { parent.error = `Unreadable parent ${file}: ${String(error)}`; lines.close(); });
		try {
			for await (const line of lines) {
				const entry = JSON.parse(line) as Entry;
				if (!parent.id) {
					if (entry.type !== "session" || !entry.id) throw new Error("Invalid session header");
					parent.id = entry.id;
				} else {
					if (!entry.id || entry.type === "session") throw new Error("Invalid session entry");
					if (wanted.has(entry.id)) {
						if (parent.signatures.has(entry.id)) throw new Error("Duplicate entry ID");
						parent.signatures.set(entry.id, shape(entry));
					}
				}
			}
			if (!parent.id) throw new Error("Missing session header");
		} catch (error) { parent.error = `Unreadable parent ${file}: ${String(error)}`; }
		finally { lines.close(); input.destroy(); }
		if (parent.signatures.size || parent.error) parents.push(parent);
	}
	return parents;
}

function boundary(entries: Entry[], parents: Parent[]): string | undefined {
	const shapes = new Map(entries.slice(1).map((entry) => [entry.id, shape(entry)]));
	const same = (parent: Parent, entry: Entry) => parent.signatures.get(entry.id)?.exact === shapes.get(entry.id)!.exact;
	const lineage = (parent: Parent, entry: Entry) => parent.signatures.get(entry.id)?.key === shapes.get(entry.id)!.key;
	const compatible = (parent: Parent, entry: Entry) => same(parent, entry) || (lineage(parent, entry) && !parent.signatures.get(entry.id)!.usage && !shapes.get(entry.id)!.usage);
	const inherited = (entry: Entry) => shapes.get(entry.id)!.usage && parents.some((parent) => same(parent, entry) || lineage(parent, entry));
	const meta = entries[0].piContextFork;
	if (meta) {
		if (meta.inherited == null) return undefined;
		const at = entries.findIndex((entry) => entry.id === meta.inherited);
		if (at < 1) throw new Error("Missing inherited entry");
		const candidates = parents.filter((parent) => parent.id === meta.parentSessionId);
		if (!candidates.some((parent) => !parent.error && entries.slice(1, at + 1).every((entry) => same(parent, entry)))) throw new Error("Parent lineage is missing or unreadable");
		return meta.inherited;
	}
	const prompts = entries.flatMap((entry, at) => WARM_PROMPTS.some((prompt) => userText(entry).startsWith(prompt)) ? [at] : []);
	if (prompts.length > 1) throw new Error("Legacy nested ancestry is ambiguous");
	if (!prompts.length) {
		const body = entries.slice(1);
		if (body.length && parents.some((parent) => !parent.error && body.every((entry) => same(parent, entry)))) return body.at(-1)!.id;
		if (body.some(inherited)) throw new Error("Inherited usage has no identifiable boundary");
		return undefined;
	}
	const prefix = entries.slice(1, prompts[0]);
	let matched = 0;
	for (const parent of parents) {
		let length = 0;
		for (const entry of prefix) { if (!compatible(parent, entry)) break; length++; }
		if (parent.error && length) throw new Error(parent.error);
		matched = Math.max(matched, length);
	}
	for (const entry of prefix.slice(0, matched).filter((entry) => !shapes.get(entry.id)!.usage)) {
		if (new Set(parents.filter((parent) => lineage(parent, entry)).map((parent) => parent.signatures.get(entry.id)!.exact)).size > 1) throw new Error("Legacy parent content is ambiguous");
	}
	if (entries.slice(matched + 1).some(inherited)) throw new Error("Legacy billed ancestry is ambiguous");
	if (prefix.slice(matched).some(billed)) throw new Error("Legacy parent lineage is missing or ambiguous");
	return matched ? prefix[matched - 1].id : undefined;
}

function verifyArchive(digest: string, agentDir: string): void {
	if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error("Invalid archive hash");
	const archive = path.join(agentDir, "pi-context", "kept", `${digest}.jsonl`);
	regular(archive);
	if (hash(fs.readFileSync(archive)) !== digest) throw new Error("Missing or corrupt full archive");
}

async function readSession(file: string): Promise<{ data: Buffer; entries: Entry[] }> {
	regular(file);
	const data = await fs.promises.readFile(file);
	return { data, entries: parse(data) };
}

/** Previews legacy repairs without writes; apply archives originals before replacing accounting copies. */
export async function migrateUsageSessions(agentDir: string, apply = false): Promise<Migration> {
	const sessions = path.join(agentDir, "sessions");
	const kept = path.join(sessions, "pi-context");
	const plan = async (): Promise<Migration> => {
		const result: Migration = { changes: [], blocked: [] };
		if (!fs.existsSync(kept)) return result;
		if (fs.lstatSync(kept).isSymbolicLink()) throw new Error(`Refusing symlink: ${kept}`);
		const files = fs.readdirSync(kept).sort().filter((name) => /^.+-[a-f0-9]{8}\.jsonl$/.test(name)).map((name) => path.join(kept, name));
		const wanted = new Set<string>();
		const legacy: { file: string; identity: string }[] = [];
		for (const file of files) {
			try {
				const source = await readStable(file);
				if (!source) continue;
				const { entries } = source;
				if (entries[0].piContextUsage) { verifyArchive(entries[0].piContextUsage.sourceHash, agentDir); continue; }
				legacy.push({ file, identity: source.identity });
				for (const entry of entries.slice(1)) wanted.add(entry.id);
			} catch (error) { if (!(error instanceof ChangedError)) result.blocked.push({ file, reason: (error as Error).message }); }
		}
		if (!legacy.length) return result;
		const parents = await parentIndex(sessionFiles(sessions), wanted);
		for (const { file, identity: before } of legacy) {
			try {
				const source = await readStable(file);
				if (source?.identity !== before) continue;
				const { data, entries } = source;
				const inherited = boundary(entries, parents);
				if (inherited !== undefined) result.changes.push({ file, sourceHash: hash(data), inherited });
			} catch (error) { if (!(error instanceof ChangedError)) result.blocked.push({ file, reason: (error as Error).message }); }
		}
		return result;
	};
	const result = await plan();
	if (!apply) return result;
	if (result.blocked.length) throw new Error(`Migration blocked: ${JSON.stringify(result.blocked)}`);
	const unchanged = async (change: Migration["changes"][number]) => {
		try {
			const source = await readStable(change.file);
			return source && hash(source.data) === change.sourceHash ? source : undefined;
		} catch (error) { if (error instanceof ChangedError) return undefined; throw error; }
	};
	const applied: Migration["changes"] = [];
	for (const change of result.changes) {
		const before = await unchanged(change);
		if (!before) continue;
		const archive = archiveSession(before.data, agentDir);
		const projected = projection(before.entries, change.sourceHash, change.inherited);
		// A file retained or resumed by a fork since planning is already current and stays as is.
		const replaced = await withUsageLock(agentDir, () => {
			if (identity(change.file) !== before.identity) return false;
			regular(archive);
			if (fs.statSync(archive).size !== before.data.length) throw new Error("Missing or corrupt full archive");
			replace(change.file, projected);
			return true;
		});
		if (replaced) applied.push({ ...change, archive });
	}
	return { ...result, changes: applied };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const args = process.argv.slice(2);
	if ((args.length !== 2 && args.length !== 3) || args[0] !== "--agent-dir" || (args.length === 3 && args[2] !== "--apply")) throw new Error("Usage: node usage-sessions.ts --agent-dir <path> [--apply]");
	console.log(JSON.stringify(await migrateUsageSessions(path.resolve(args[1]), args[2] === "--apply"), null, 2));
}
