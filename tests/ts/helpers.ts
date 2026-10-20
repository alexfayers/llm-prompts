// Loads a pi extension against fake pi / ctx / ui objects that record what the extension registers and does.
import fs from "node:fs";
import { after, afterEach, before, beforeEach, mock } from "node:test";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const EXTENSIONS_DIR = join(import.meta.dirname, "../../src/llm_prompts/prompts/pi/extensions");

export type Handler = (event: any, ctx: any) => unknown;
export type Tool = { name: string; execute: (id: string, params: any, signal?: AbortSignal, onUpdate?: unknown, ctx?: any) => Promise<any> } & Record<string, any>;
export type Command = { handler: (args: string, ctx: any) => Promise<void> | void } & Record<string, any>;

export interface FakeCtx {
	cwd: string;
	hasUI: boolean;
	model?: unknown;
	/** [message, level] pairs passed to ui.notify */
	notices: [string, string | undefined][];
	/** [key, text] pairs passed to ui.setStatus */
	statuses: [string, string | undefined][];
	/** session files passed to switchSession */
	switched: string[];
	/** argument lists passed to sendUserMessage on the replacement session */
	continued: unknown[][];
	[key: string]: any;
}

export interface FakePi {
	handlers: Record<string, Handler[]>;
	commands: Record<string, Command>;
	tools: Record<string, Tool>;
	/** [content, options] pairs passed to sendUserMessage */
	sent: unknown[][];
	/** [event, payload] pairs put on the event bus */
	emitted: [string, unknown][];
	activeTools: string[];
	allTools: Record<string, any>[];
	/** slash command names reported by getCommands */
	commandNames: string[];
	model?: unknown;
	thinking?: string;
	[key: string]: any;
}

export interface LoadOptions {
	/** Directory returned by getAgentDir (sets PI_CODING_AGENT_DIR). */
	agentDir?: string;
	/** Named exports to replace in a module, keyed by specifier (other exports stay real). Applies to this load only. */
	mocks?: Record<string, Record<string, unknown>>;
	/** Initial state for the fake pi. */
	pi?: Partial<FakePi>;
	/** Initial state for the default ctx. */
	ctx?: Partial<FakeCtx>;
}

export interface LoadedExtension {
	pi: FakePi & ExtensionAPI;
	ctx: FakeCtx & ExtensionContext;
	module: Record<string, any>;
	handlers: FakePi["handlers"];
	commands: FakePi["commands"];
	tools: FakePi["tools"];
	/** Creates another fake ctx, with the given fields overriding the defaults. */
	makeCtx(overrides?: Partial<FakeCtx>): FakeCtx & ExtensionContext;
	/** Runs every handler for the event in order and returns the last defined result. */
	fire(event: string, payload?: unknown, ctx?: FakeCtx): Promise<any>;
	/** Runs a registered slash command. */
	runCommand(name: string, args?: string, ctx?: FakeCtx): Promise<void>;
	/** Runs a registered tool's execute. */
	callTool(name: string, params?: unknown, ctx?: FakeCtx): Promise<any>;
}

export function makeCtx(overrides: Partial<FakeCtx> = {}): FakeCtx & ExtensionContext {
	const ctx: FakeCtx = {
		cwd: "/",
		hasUI: true,
		notices: [],
		statuses: [],
		switched: [],
		continued: [],
		ui: {
			notify: (message: string, level?: string) => ctx.notices.push([message, level]),
			setStatus: (key: string, text?: string) => ctx.statuses.push([key, text]),
		},
		sessionManager: {
			getSessionId: () => "session-id",
			getSessionFile: () => join(ctx.cwd, "s.jsonl"),
			usesDefaultSessionDir: () => true,
		},
		async switchSession(path: string, options?: { withSession?: (replaced: unknown) => Promise<void> }) {
			ctx.switched.push(path);
			await options?.withSession?.({ sendUserMessage: async (...args: unknown[]) => ctx.continued.push(args) });
			return { cancelled: false };
		},
		...overrides,
	};
	return ctx as FakeCtx & ExtensionContext;
}

function makePi(state: Partial<FakePi>): FakePi & ExtensionAPI {
	const pi: FakePi = {
		handlers: {},
		commands: {},
		tools: {},
		sent: [],
		emitted: [],
		activeTools: [],
		allTools: [],
		commandNames: [],
		...state,
		events: {
			emit: (event: string, payload: unknown) => pi.emitted.push([event, structuredClone(payload)]),
			on: () => () => {},
		},
		on: (event: string, handler: Handler) => void (pi.handlers[event] ??= []).push(handler),
		registerTool: (tool: Tool) => void (pi.tools[tool.name] = tool),
		registerCommand: (name: string, command: Command) => void (pi.commands[name] = command),
		getActiveTools: () => pi.activeTools,
		getAllTools: () => pi.allTools,
		setActiveTools: (names: string[]) => void (pi.activeTools = names),
		getCommands: () => pi.commandNames.map((name) => ({ name })),
		getThinkingLevel: () => pi.thinking,
		setThinkingLevel: (level: string) => void (pi.thinking = level),
		setModel: async (model: unknown) => ((pi.model = model), true),
		sendUserMessage: async (...args: unknown[]) => void pi.sent.push(args),
	};
	return pi as FakePi & ExtensionAPI;
}

let loads = 0;
const active = new Map<string, { restore(): void }>();

/** Loads src/llm_prompts/prompts/pi/extensions/<name>.ts and runs its default export against a fake pi. */
export async function loadExtension(name: string, options: LoadOptions = {}): Promise<LoadedExtension> {
	if (options.agentDir) process.env.PI_CODING_AGENT_DIR = options.agentDir;
	for (const [specifier, exports] of Object.entries(options.mocks ?? {})) {
		active.get(specifier)?.restore();
		const { default: realDefault, ...real } = await import(specifier);
		active.set(specifier, mock.module(specifier, { namedExports: { ...real, ...exports }, defaultExport: { ...realDefault, ...exports } }));
	}
	const module = await import(`${pathToFileURL(join(EXTENSIONS_DIR, `${name}.ts`))}?load=${loads++}`);
	const pi = makePi(options.pi ?? {});
	await module.default(pi);
	const ctx = makeCtx(options.ctx);
	return {
		pi,
		ctx,
		module,
		handlers: pi.handlers,
		commands: pi.commands,
		tools: pi.tools,
		makeCtx,
		async fire(event, payload = {}, using = ctx) {
			let result: unknown;
			for (const handler of pi.handlers[event] ?? []) result = (await handler(payload, using)) ?? result;
			return result;
		},
		runCommand: async (command, args = "", using = ctx) => void (await pi.commands[command].handler(args, using)),
		callTool: (tool, params = {}, using = ctx) => pi.tools[tool].execute("call-id", params, undefined, undefined, using),
	};
}

/** Restores the mocked modules; call from an `after` hook. */
export function restoreMocks(): void {
	for (const context of active.values()) context.restore();
	active.clear();
}

type EnvVars = Record<string, string | undefined>;

function applyEnv(vars: EnvVars): EnvVars {
	const previous: EnvVars = {};
	for (const [key, value] of Object.entries(vars)) {
		previous[key] = process.env[key];
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
	return previous;
}

/** Sets the environment variables before each test and restores them after each test. */
export function useEnv(vars: EnvVars | (() => EnvVars)): void {
	let previous: EnvVars = {};
	beforeEach(() => void (previous = applyEnv(typeof vars === "function" ? vars() : vars)));
	afterEach(() => void applyEnv(previous));
}

export interface MemoryFs {
	/** Every path under this directory is served from memory; other paths reach the real filesystem. */
	root: string;
	read(file: string): string;
	write(file: string, text: string): void;
	append(file: string, text: string): void;
	/** Creates the directory and its parents; mtimeMs defaults to now. */
	mkdir(dir: string, mtimeMs?: number): void;
	touch(path: string, mtimeMs: number): void;
	remove(path: string): void;
	/** Writes <agentDir>/pi-herdsman/runtime/mailboxes-v5/<id>/state.json and returns the mailbox directory. */
	writeMailboxState(agentDir: string, id: string, state?: unknown): string;
}

type Entry = { text?: string; mtimeMs: number };

const MEMORY_ROOT = "/mem";

/** Serves the paths under MemoryFs.root from memory for the tests in this file, starting each test empty. */
export function useMemoryFs(): MemoryFs {
	const entries = new Map<string, Entry>();
	const mocks: { mock: { restore(): void } }[] = [];
	const missing = (file: string) => Object.assign(new Error(`ENOENT: no such file or directory, '${file}'`), { code: "ENOENT" });
	const file = (path: string) => {
		const entry = entries.get(path);
		if (entry?.text === undefined) throw missing(path);
		return entry.text;
	};
	const mkdir = (dir: string, mtimeMs = Date.now()) => {
		for (let at = dir; at.startsWith(`${MEMORY_ROOT}/`); at = dirname(at)) entries.set(at, { mtimeMs: at === dir ? mtimeMs : (entries.get(at)?.mtimeMs ?? mtimeMs) });
	};
	const write = (path: string, text: string) => {
		mkdir(dirname(path));
		entries.set(path, { text, mtimeMs: Date.now() });
	};
	const remove = (path: string) => {
		for (const key of [...entries.keys()]) if (key === path || key.startsWith(`${path}/`)) entries.delete(key);
	};
	const list = (dir: string) => {
		if (!entries.has(dir) && dir !== MEMORY_ROOT) throw missing(dir);
		return [...entries.keys()].filter((key) => dirname(key) === dir).map((key) => key.slice(dir.length + 1));
	};
	const stat = (path: string, options?: { throwIfNoEntry?: boolean }) => {
		const entry = entries.get(path);
		if (!entry) {
			if (options?.throwIfNoEntry === false) return undefined;
			throw missing(path);
		}
		return { size: Buffer.byteLength(entry.text ?? ""), mtimeMs: entry.mtimeMs, isDirectory: () => entry.text === undefined };
	};
	const fakes: Record<string, (...args: any[]) => unknown> = {
		readFileSync: file,
		writeFileSync: write,
		readdirSync: list,
		existsSync: (path: string) => entries.has(path),
		statSync: stat,
		mkdirSync: (dir: string) => void mkdir(dir),
		rmSync: (path: string, options?: { force?: boolean }) => {
			if (!entries.has(path) && !options?.force) throw missing(path);
			remove(path);
		},
	};
	const promiseFakes: Record<string, (...args: any[]) => unknown> = {
		stat: async (path: string) => stat(path),
		readFile: async (path: string) => file(path),
		readdir: async (dir: string) => list(dir),
		open: async (path: string) => ({
			read: async (buffer: Buffer, offset: number, length: number, position: number) =>
				void Buffer.from(file(path)).copy(buffer, offset, position, position + length),
			close: async () => {},
		}),
	};
	const intercept = (target: any, name: string, fake: (...args: any[]) => unknown) => {
		const real = target[name].bind(target);
		mocks.push(mock.method(target, name, (path: unknown, ...args: unknown[]) => (typeof path === "string" && path.startsWith(`${MEMORY_ROOT}/`) ? fake(path, ...args) : real(path, ...args))));
	};

	before(() => {
		for (const [name, fake] of Object.entries(fakes)) intercept(fs, name, fake);
		for (const [name, fake] of Object.entries(promiseFakes)) intercept(fs.promises, name, fake);
	});
	beforeEach(() => entries.clear());
	after(() => mocks.forEach((context) => context.mock.restore()));

	return {
		root: MEMORY_ROOT,
		read: file,
		write,
		append: (path, text) => write(path, (entries.get(path)?.text ?? "") + text),
		mkdir,
		touch: (path, mtimeMs) => void (entries.get(path)!.mtimeMs = mtimeMs),
		remove,
		writeMailboxState(agentDir, id, state = {}) {
			const mailbox = join(agentDir, "pi-herdsman/runtime/mailboxes-v5", id);
			write(join(mailbox, "state.json"), typeof state === "string" ? state : JSON.stringify(state));
			return mailbox;
		},
	};
}

export interface FakeEvents {
	/** [event, payload] pairs passed to emit */
	emitted: [string, unknown][];
	on(event: string, handler: (payload: any) => void): () => void;
	emit(event: string, payload?: unknown): void;
}

/** An event bus whose emit records the payload and calls the subscribed handlers. */
export function makeEvents(): FakeEvents {
	const listeners: Record<string, ((payload: any) => void)[]> = {};
	const events: FakeEvents = {
		emitted: [],
		on: (event, handler) => {
			(listeners[event] ??= []).push(handler);
			return () => void (listeners[event] = listeners[event].filter((h) => h !== handler));
		},
		emit: (event, payload) => {
			events.emitted.push([event, structuredClone(payload)]);
			for (const handler of listeners[event] ?? []) handler(payload);
		},
	};
	return events;
}
