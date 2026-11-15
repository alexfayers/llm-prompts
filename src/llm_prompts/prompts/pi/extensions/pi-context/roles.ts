// Defines the roles of delegated pi sessions and the tool_call guard that enforces them.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { ExtensionContext, ToolCallEvent } from "@earendil-works/pi-coding-agent";

export type Role = {
	name: "reader" | "writer" | "btw";
	card: string;
	/** Allowed non-MCP tool names, as globs. */
	tools: string[];
	/** Allowed MCP tool names (`mcp__<server>__<tool>`), as globs. */
	mcp: string[];
	skills: string[];
	/** The role writes in its own worktree. */
	writes: boolean;
};

export type Block = { block: true; reason: string };

const WARM_OPENING = "You are the delegate that the conversation above asked to fork, so do not call fork.";
const COLD_OPENING = "You are a delegate given one self-contained task, so do not call fork.";
const OUTCOME = "Open the final reply with `OUTCOME <code> ref:<ref>`. Put any question for the user on a line starting `ASK:` and do not ask the user directly.";
const READ_TOOLS = ["read", "grep", "find", "ls", "bash", "codemode", "lsp_diagnostics", "web_search", "fetch_content", "get_search_content", "result_fetch", "result_query"];
const READ_MCP = [
	"mcp__semble__*",
	"mcp__memory__read_*",
	"mcp__memory__search_*",
	"mcp__memory__get_*",
	"mcp__memory__list_*",
];

export const ROLES: Record<Role["name"], Role> = {
	reader: {
		name: "reader",
		card: `${WARM_OPENING} You are read-only. Investigate and report. Do not change files, git state or memory. ${OUTCOME}`,
		tools: READ_TOOLS,
		mcp: READ_MCP,
		skills: [],
		writes: false,
	},
	writer: {
		name: "writer",
		card: `${WARM_OPENING} You work in your own git worktree. Commit your work there. Do not touch other paths or memory. ${OUTCOME}`,
		tools: [...READ_TOOLS, "edit", "write", "process"],
		mcp: READ_MCP,
		skills: [],
		writes: true,
	},
	btw: {
		name: "btw",
		card: "You answer one side question for the user. Read-only. Answer briefly and do not continue the main task.",
		tools: READ_TOOLS,
		mcp: READ_MCP,
		skills: [],
		writes: false,
	},
};

/** The role card for a worker that has no conversation above it. */
export const coldCard = ({ card }: Role): string => card.replace(WARM_OPENING, COLD_OPENING);

const globRegExp = (pattern: string) => new RegExp(`^${pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*")}$`);
const matches = (globs: string[], name: string) => globs.some((glob) => globRegExp(glob).test(name));

const WRITE_TOOLS = ["edit", "write"];
const SHELL_TOOLS = ["bash", "process"];
const PATH_KEYS = ["path", "file_path"];
const PATH_ARGS = [...PATH_KEYS, "cwd"];
const startsProcess = (toolName: string, input: Record<string, unknown>) => toolName === "process" && input.action === "start";

const inside = (root: string, target: string) => target === root || target.startsWith(root + path.sep);
const realOr = (target: string) => {
	try {
		return fs.realpathSync(target);
	} catch {
		return target;
	}
};
const escapeRegExp = (text: string) => text.replace(/[.+?^${}()|[\]\\]/g, "\\$&");

/** Every absolute spelling of `target`: itself, its real path, and each of those through the home directory's real path or symlink. */
function aliasesOf(target: string): string[] {
	const homes = [...new Set([os.homedir(), realOr(os.homedir())])];
	const known = [...new Set([target, realOr(target)])];
	return [...new Set(known.flatMap((alias) => [alias, ...homes.filter((home) => inside(home, alias)).flatMap((from) => homes.map((to) => to + alias.slice(from.length)))]))];
}

/** The ways a shell command can name `dir`: its aliases, and the aliases under the home directory spelled `~`, `$HOME` and `${HOME}`. */
const shellSpellings = (dir: string) => aliasesOf(dir).flatMap((alias) => [alias, ...(inside(os.homedir(), alias) ? ["~", "$HOME", "${HOME}"].map((home) => home + alias.slice(os.homedir().length)) : [])]);

export const expandHome = (target: string) => (target === "~" || target.startsWith("~/") ? path.join(os.homedir(), target.slice(1)) : target);

/** Matches any shell spelling of the given directories as a whole path or path prefix. */
const shellPathPattern = (dirs: string[]) => new RegExp(`(?<![\\w.~/$])(?:${dirs.flatMap(shellSpellings).sort((a, b) => b.length - a.length).map(escapeRegExp).join("|")})(?![\\w.-])`, "g");

/** Whether the shell command names `repo` other than as part of `worktree` or as an `ln` target. */
function namesMainCheckout(command: string, worktree: string, repo: string): boolean {
	const worktreePath = shellPathPattern([worktree]);
	const inWorktree = (offset: number) => [...command.matchAll(worktreePath)].some((match) => match.index === offset);
	return [...command.matchAll(shellPathPattern([repo]))].some(({ index, 0: spelling }) => !inWorktree(index) && !isLinkTarget(command, index, spelling.length));
}

/** Returns a block when the role may not make this call. A role with `writes` may write only inside its worktree, and may not name its main checkout `repo` in a shell command. */
export function decide(role: Role, toolName: string, input: Record<string, unknown>, worktree?: string, repo?: string): Block | undefined {
	const allowed = matches(toolName.startsWith("mcp__") ? role.mcp : role.tools, toolName);
	if (!allowed) return { block: true, reason: `role ${role.name} may not use ${toolName}` };
	if (!role.writes) return undefined;
	if (worktree && repo && SHELL_TOOLS.includes(toolName) && typeof input.command === "string" && namesMainCheckout(input.command, worktree, repo)) {
		return { block: true, reason: `role ${role.name} may not name the main checkout ${repo} in a command, even to read it. Use your worktree ${worktree} instead` };
	}
	if (!(WRITE_TOOLS.includes(toolName) || startsProcess(toolName, input))) return undefined;
	if (!worktree) return { block: true, reason: `role ${role.name} has no worktree to write in` };
	const target = PATH_ARGS.map((key) => input[key]).find((value) => typeof value === "string");
	const resolved = typeof target === "string" ? path.resolve(worktree, expandHome(target)) : undefined;
	if (resolved && aliasesOf(worktree).some((root) => inside(root, resolved))) return undefined;
	const main = resolved && repo ? aliasesOf(repo).find((root) => inside(root, resolved)) : undefined;
	if (main !== undefined && resolved) return { block: true, reason: `role ${role.name} may not change the main checkout ${repo}. Use ${worktree + resolved.slice(main.length)} in your worktree instead` };
	return { block: true, reason: `role ${role.name} may write only inside ${worktree}` };
}

const shellQuote = (text: string) => `'${text.replaceAll("'", "'\\''")}'`;

const SEPARATOR = /[;&|\n]/;

/** Whether the text at `offset` is an operand of an `ln` command other than its last, which names what the link points at, not a path it writes. */
function isLinkTarget(command: string, offset: number, length: number): boolean {
	const start = Math.max(...[";", "&", "|", "\n"].map((separator) => command.lastIndexOf(separator, offset - 1))) + 1;
	const rest = command.slice(offset + length).replace(/^\S*/, "");
	const end = rest.search(SEPARATOR);
	return /^\s*ln\s/.test(command.slice(start, offset)) && /\S/.test(end === -1 ? rest : rest.slice(0, end));
}

/** Points main-directory paths in the call at the worktree, in place. Bash and started processes also run in the worktree. */
export function rewriteForWorktree(toolName: string, input: Record<string, unknown>, worktree: string, mainCwd: string): void {
	if ((toolName === "bash" || toolName === "process") && typeof input.command === "string") {
		const command = input.command.replace(shellPathPattern([worktree, mainCwd]), (spelling, offset: number, whole: string) => (aliasesOf(worktree).includes(spelling) || isLinkTarget(whole, offset, spelling.length) ? spelling : worktree));
		const prefix = `cd ${shellQuote(worktree)} && `;
		input.command = toolName === "process" || command.startsWith(prefix) ? command : prefix + command;
	}
	if (toolName === "bash") return;
	for (const key of PATH_ARGS) {
		const value = typeof input[key] === "string" ? expandHome(input[key]) : undefined;
		if (value === undefined || aliasesOf(worktree).some((root) => inside(root, value))) continue;
		const main = aliasesOf(mainCwd).find((root) => inside(root, value));
		input[key] = main === undefined ? path.resolve(worktree, value) : worktree + value.slice(main.length);
	}
	if (startsProcess(toolName, input) && !(typeof input.cwd === "string" && aliasesOf(worktree).some((root) => inside(root, input.cwd as string)))) input.cwd = worktree;
}

const optionalString = (value: unknown) => (typeof value === "string" ? value : undefined);

function readHandshake(file: string): { role: Role; worktree?: string; repo?: string } | undefined {
	try {
		const { role, worktree, repo } = JSON.parse(fs.readFileSync(file, "utf8")) as { role?: string; worktree?: unknown; repo?: unknown };
		if (role === undefined || !Object.hasOwn(ROLES, role)) return undefined;
		return { role: ROLES[role as Role["name"]], worktree: optionalString(worktree), repo: optionalString(repo) };
	} catch {
		return undefined;
	}
}

/** Builds the tool_call handler of a delegated session from its handshake file. A bad handshake blocks every call. */
export function childGuard(handshakeFile: string): (event: ToolCallEvent, ctx: ExtensionContext) => Block | undefined {
	const child = readHandshake(handshakeFile);
	return ({ toolName, input }, { cwd }) => {
		if (!child) return { block: true, reason: `pi-context handshake ${handshakeFile} is unreadable or names an unknown role` };
		const worktree = child.role.writes ? child.worktree : undefined;
		if (worktree) rewriteForWorktree(toolName, input, worktree, cwd);
		return decide(child.role, toolName, input, worktree, child.repo);
	};
}
