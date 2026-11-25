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

export type ReadOnlyAgentDir = { dir: string; dispose: () => void };

/** Makes a directory outside `agentDir` that links each entry of `agentDir` except settings.json and holds settings that leave out the language server extension, so a read-only delegate started with it as its agent directory starts no language server. `dispose` removes it, once, and also runs when the process exits. */
export function readOnlyAgentDir(agentDir: string): ReadOnlyAgentDir {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pi-context-agent-"));
	const dispose = () => {
		process.off("exit", dispose);
		fs.rmSync(dir, { recursive: true, force: true });
	};
	process.on("exit", dispose);
	try {
		for (const name of fs.readdirSync(agentDir)) if (name !== "settings.json") fs.symlinkSync(path.join(agentDir, name), path.join(dir, name));
		let settings: Record<string, unknown> = {};
		try { settings = JSON.parse(fs.readFileSync(path.join(agentDir, "settings.json"), "utf8")); } catch { /* no settings to copy */ }
		for (const key of RESOURCE_KEYS) {
			if (!Array.isArray(settings[key])) continue;
			const kept = ["packages", "extensions"].includes(key) ? settings[key].filter((entry) => !sourceOf(entry).includes(LSP_EXTENSION)) : settings[key];
			settings[key] = kept.map((entry: unknown) => absolute(agentDir, entry));
		}
		fs.writeFileSync(path.join(dir, "settings.json"), JSON.stringify(settings), { mode: 0o600 });
	} catch (error) {
		dispose();
		throw error;
	}
	return { dir, dispose };
}
