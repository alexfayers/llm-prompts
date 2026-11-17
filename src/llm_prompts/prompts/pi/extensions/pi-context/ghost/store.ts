// Reads and writes ghost files under the agent directory, private to the user.
import { chmod, mkdir, readdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { Ghost } from "./model.ts";

export const NAME = /^[a-z0-9][a-z0-9-]{0,39}$/;
const PRIVATE_DIR = 0o700;
const PRIVATE_FILE = 0o600;

const ghostsRoot = () => join(getAgentDir(), "ghosts");
export const ghostPath = (key: string, name: string, draft = false) => join(ghostsRoot(), key, `${name}${draft ? ".draft" : ""}.json`);

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isCheck = (check: unknown) =>
	check === null ||
	(isObject(check) &&
		typeof check.isError === "boolean" &&
		(check.output === undefined || (isObject(check.output) && (typeof check.output.exact === "string" || typeof check.output.regex === "string" || check.output.empty === true))));
const isStep = (step: unknown) => isObject(step) && typeof step.tool === "string" && isObject(step.args) && typeof step.isError === "boolean" && isCheck(step.check);
const isParam = (param: unknown) => isObject(param) && typeof param.default === "string" && typeof param.pattern === "string";

/** Parses ghost JSON, throwing when it is not a ghost. */
export function parseGhost(text: string): Ghost {
	const data: unknown = JSON.parse(text);
	const ok =
		isObject(data) &&
		data.version === 1 &&
		[data.name, data.repoKey, data.branch, data.piVersion].every((field) => typeof field === "string") &&
		(data.approvedHash === undefined || typeof data.approvedHash === "string") &&
		isObject(data.params) &&
		Object.values(data.params).every(isParam) &&
		Array.isArray(data.steps) &&
		data.steps.every(isStep);
	if (!ok) throw new Error("it is not a ghost file");
	return data as unknown as Ghost;
}

/** Writes the ghost atomically, and creates its directories private to the user. */
export async function writeGhost(file: string, ghost: Ghost): Promise<void> {
	await mkdir(dirname(file), { recursive: true, mode: PRIVATE_DIR });
	await Promise.all([chmod(ghostsRoot(), PRIVATE_DIR), chmod(dirname(file), PRIVATE_DIR)]);
	const partial = `${file}.${process.pid}.tmp`;
	await writeFile(partial, JSON.stringify(ghost, null, 2), { mode: PRIVATE_FILE });
	await rename(partial, file);
}

const missing = (error: unknown) => (error as NodeJS.ErrnoException).code === "ENOENT";

/** Reads a ghost file, or undefined when there is none. */
export async function readGhost(file: string): Promise<Ghost | undefined> {
	const text = await readFile(file, "utf8").catch((error) => (missing(error) ? undefined : Promise.reject(error)));
	if (text === undefined) return undefined;
	try {
		return parseGhost(text);
	} catch (error) {
		throw new Error(`${file}: ${error instanceof SyntaxError ? "it is not valid JSON" : (error as Error).message}`);
	}
}

/** The names of the repository's saved ghosts, without drafts. */
export async function listGhosts(key: string): Promise<string[]> {
	const files = await readdir(dirname(ghostPath(key, "x"))).catch((error) => (missing(error) ? [] : Promise.reject(error)));
	return files.filter((file) => file.endsWith(".json") && !file.endsWith(".draft.json")).map((file) => file.slice(0, -".json".length)).sort();
}

export const removeGhost = (file: string) => rm(file, { force: true });
