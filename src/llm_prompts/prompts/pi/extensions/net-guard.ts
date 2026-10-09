import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import { syncBuiltinESMExports } from "node:module";
import net from "node:net";
import path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

type Mode = "block" | "log";
type Plugin = { name: string; root: string };
type Dispatcher = { dispatch: (options: { origin?: string | URL }, handler: unknown) => boolean };

const INSTALLED = Symbol.for("llm-prompts.net-guard");
const DISPATCHER_KEYS = ["undici.globalDispatcher.1", "undici.globalDispatcher.2"];
const STACK_DEPTH = 100;
const ALWAYS_ALLOWED = ["net-guard"];
const LOCAL_HOST = /^(localhost|.*\.localhost|127(\.\d+){3}|::1|\[::1\]|0\.0\.0\.0|)$/i;
const FRAME_PATH = /(?:\(|\s)(?:file:\/\/)?(\/[^\s():]+?)(?::\d+){0,2}\)?$/;

const agentDir = getAgentDir();
const configPath = path.join(agentDir, "net-guard.json");
const logPath = path.join(agentDir, "net-guard.log");

let mode: Mode = "block";
let allow: RegExp[] = [];
let plugins: Plugin[] = [];
let extensionRoots: string[] = [];
let notifyContext: ExtensionContext | undefined;
const notified = new Set<string>();
const patchedDispatchers = new WeakSet<object>();

function readJson(file: string): Record<string, unknown> {
	try {
		return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
	} catch {
		return {};
	}
}

function globToRegExp(pattern: string): RegExp {
	const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
	return new RegExp(`^${escaped}$`, "i");
}

function pluginFromSource(source: string, baseDir: string): Plugin | undefined {
	if (source.startsWith("npm:")) {
		const name = source.slice(4).replace(/(?<=.)@[^/@]*$/, "");
		return { name, root: `/node_modules/${name}/` };
	}
	const remote = source.match(/^(?:git\+)?(?:[a-z+]+:\/\/)?(?:[^@/]+@)?([^/:]+)[/:](.+?)(?:\.git)?(?:@[^/]+)?$/);
	if (remote && !source.startsWith(".") && !source.startsWith("/") && !source.startsWith("~")) {
		return { name: path.basename(remote[2]), root: `/git/${remote[1]}/${remote[2]}/` };
	}
	const local = path.resolve(baseDir, source.replace(/^~/, process.env.HOME ?? "~"));
	return { name: path.basename(local), root: `${local}/` };
}

function loadPlugins(cwd: string): Plugin[] {
	const found: Plugin[] = [];
	for (const [settingsFile, baseDir] of [
		[path.join(agentDir, "settings.json"), agentDir],
		[path.join(cwd, ".pi", "settings.json"), path.join(cwd, ".pi")],
	]) {
		const packages = readJson(settingsFile).packages;
		if (!Array.isArray(packages)) continue;
		for (const entry of packages) {
			const source = typeof entry === "string" ? entry : (entry as { source?: string })?.source;
			const plugin = source ? pluginFromSource(source, baseDir) : undefined;
			if (plugin) found.push(plugin);
		}
	}
	return found;
}

function loadConfig(cwd: string): void {
	const config = readJson(configPath);
	mode = config.mode === "log" ? "log" : "block";
	const allowed = Array.isArray(config.allow) ? config.allow.map(String) : [];
	allow = [...allowed, ...ALWAYS_ALLOWED].map(globToRegExp);
	plugins = loadPlugins(cwd);
	extensionRoots = [path.join(agentDir, "extensions"), path.join(cwd, ".pi", "extensions")].map((dir) => `${dir}/`);
}

function pluginOfFrame(file: string): string | undefined {
	const plugin = plugins.find((candidate) => file.includes(candidate.root));
	if (plugin) return plugin.name;
	const root = extensionRoots.find((dir) => file.startsWith(dir));
	return root ? file.slice(root.length).split("/")[0].replace(/\.[cm]?[tj]s$/, "") : undefined;
}

function captureStack(): string {
	const previous = Error.stackTraceLimit;
	Error.stackTraceLimit = STACK_DEPTH;
	const { stack } = new Error();
	Error.stackTraceLimit = previous;
	return stack ?? "";
}

function blockedPlugin(): string | undefined {
	for (const line of captureStack().split("\n").slice(1)) {
		const file = line.match(FRAME_PATH)?.[1];
		const name = file ? pluginOfFrame(file) : undefined;
		if (name && !allow.some((pattern) => pattern.test(name))) return name;
	}
	return undefined;
}

function record(plugin: string, kind: string, host: string): void {
	const entry = { time: new Date().toISOString(), plugin, kind, host, action: mode };
	try {
		fs.appendFileSync(logPath, `${JSON.stringify(entry)}\n`);
	} catch {
		// logging is best effort
	}
	if (!notified.has(plugin)) {
		notified.add(plugin);
		notifyContext?.ui.notify(`net-guard: ${mode === "block" ? "blocked" : "saw"} ${plugin} -> ${host}`, "warning");
	}
}

function guard(kind: string, host: string): void {
	if (LOCAL_HOST.test(host)) return;
	const plugin = blockedPlugin();
	if (!plugin) return;
	record(plugin, kind, host);
	if (mode === "block") {
		throw new Error(`net-guard: blocked ${kind} to ${host} from plugin ${plugin}; allow it in ${configPath}`);
	}
}

function hostOfUrl(target: unknown): string {
	try {
		const raw = target instanceof URL ? target : new URL(typeof target === "string" ? target : String((target as Request).url));
		return raw.hostname;
	} catch {
		return "unknown";
	}
}

function hostOfOptions(options: { hostname?: string; host?: string; socketPath?: string; path?: string } | undefined): string {
	if (options?.socketPath) return "";
	return options?.hostname ?? options?.host ?? "localhost";
}

function hostOfRequestArgs(args: unknown[]): string {
	const [first, second] = args;
	if (typeof first === "string" || first instanceof URL) {
		return typeof second === "object" && second && "hostname" in second ? hostOfOptions(second as Parameters<typeof hostOfOptions>[0]) : hostOfUrl(first);
	}
	return hostOfOptions(first as Parameters<typeof hostOfOptions>[0]);
}

function hostOfConnectArgs(args: unknown[]): string {
	const first = Array.isArray(args[0]) ? args[0][0] : args[0];
	if (typeof first === "string") return "";
	if (typeof first === "number") return typeof args[1] === "string" ? args[1] : "localhost";
	return hostOfOptions(first as Parameters<typeof hostOfOptions>[0]);
}

function wrapRequests(module: typeof http | typeof https, label: string): void {
	for (const method of ["request", "get"] as const) {
		const original = module[method] as (...args: unknown[]) => unknown;
		(module as unknown as Record<string, unknown>)[method] = function (this: unknown, ...args: unknown[]) {
			guard(`${label}.${method}`, hostOfRequestArgs(args));
			return original.apply(this, args);
		};
	}
}

function wrapSocketConnect(): void {
	const original = net.Socket.prototype.connect as (...args: unknown[]) => net.Socket;
	net.Socket.prototype.connect = function (this: net.Socket, ...args: unknown[]) {
		try {
			guard("net.connect", hostOfConnectArgs(args));
		} catch (error) {
			process.nextTick(() => this.destroy(error as Error));
			return this;
		}
		return original.apply(this, args);
	} as typeof net.Socket.prototype.connect;
}

function wrapFetch(): void {
	let current = globalThis.fetch;
	const wrap = (original: typeof fetch): typeof fetch =>
		function (this: unknown, input, init) {
			try {
				guard("fetch", hostOfUrl(input));
			} catch (error) {
				return Promise.reject(error);
			}
			return original.call(this, input, init);
		};
	let wrapped = wrap(current);
	Object.defineProperty(globalThis, "fetch", {
		configurable: true,
		enumerable: true,
		get: () => wrapped,
		set: (value: typeof fetch) => {
			current = value;
			wrapped = wrap(current);
		},
	});
}

function patchDispatchers(): void {
	for (const key of DISPATCHER_KEYS) {
		const dispatcher = (globalThis as Record<symbol, unknown>)[Symbol.for(key)] as Dispatcher | undefined;
		if (!dispatcher || typeof dispatcher.dispatch !== "function" || patchedDispatchers.has(dispatcher)) continue;
		patchedDispatchers.add(dispatcher);
		const original = dispatcher.dispatch;
		dispatcher.dispatch = function (this: Dispatcher, options, handler) {
			guard("undici", hostOfUrl(options.origin ?? ""));
			return original.call(this, options, handler);
		};
	}
}

function install(): void {
	const globals = globalThis as Record<symbol, unknown>;
	if (globals[INSTALLED]) return;
	globals[INSTALLED] = true;
	wrapRequests(http, "http");
	wrapRequests(https, "https");
	wrapSocketConnect();
	wrapFetch();
	syncBuiltinESMExports();
}

export default function (pi: ExtensionAPI) {
	loadConfig(process.cwd());
	install();
	patchDispatchers();
	pi.on("session_start", (_event, ctx) => {
		notifyContext = ctx;
		loadConfig(ctx.cwd);
		patchDispatchers();
	});
	pi.on("before_agent_start", () => patchDispatchers());
}
