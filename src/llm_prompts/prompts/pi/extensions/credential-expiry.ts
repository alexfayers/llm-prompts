import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";

const HTTP_ONLY_PREFIX = "#HttpOnly_";
const EXPIRY_FIELD = 4;
const MIN_FIELDS = 5;

export function parseExpiry(text: string, domain: string): number | undefined {
	const wanted = domain.toLowerCase();
	let soonest: number | undefined;
	for (const raw of text.split("\n")) {
		const line = raw.startsWith(HTTP_ONLY_PREFIX) ? raw.slice(HTTP_ONLY_PREFIX.length) : raw;
		if (line.startsWith("#")) continue;
		const fields = line.split("\t");
		if (fields.length < MIN_FIELDS || !fields[0].toLowerCase().includes(wanted)) continue;
		const expiry = Number(fields[EXPIRY_FIELD]);
		if (Number.isFinite(expiry) && expiry > 0 && (soonest === undefined || expiry < soonest)) soonest = expiry;
	}
	return soonest;
}

const CONFIG_FILE = "credential-expiry.json";
const MS_PER_SECOND = 1000;
const USAGE = "Usage: /credential-expiry [on|off]";
const LABEL = "mw";
const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;
const WARN_STYLE = "\x1b[33m";
const EXPIRED_STYLE = "\x1b[31m";
const RESET_STYLE = "\x1b[0m";

function styled(style: string, text: string): string {
	return `${style}${text}${RESET_STYLE}`;
}

function formatDuration(seconds: number): string {
	const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
	if (minutes < 1) return "<1m";
	const hours = Math.floor(minutes / MINUTES_PER_HOUR);
	if (hours < 1) return `${minutes}m`;
	return `${hours}h${String(minutes % MINUTES_PER_HOUR).padStart(2, "0")}m`;
}

export function formatRemaining(expiry: number | undefined, now: number, warnSeconds: number): string {
	const left = expiry === undefined ? 0 : expiry - now;
	if (left <= 0) return styled(EXPIRED_STYLE, `${LABEL} expired`);
	const text = `${LABEL} ${formatDuration(left)}`;
	return left < warnSeconds ? styled(WARN_STYLE, text) : text;
}

const DEFAULT_WARN_SECONDS = 3600;
const DEFAULT_INTERVAL_SECONDS = 60;
const MIN_INTERVAL_SECONDS = 10;

export type Config = { enabled: boolean; warnSeconds: number; cookiePath: string; domain: string; intervalSeconds: number };

function readJson(file: string): Record<string, unknown> {
	try {
		return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
	} catch {
		return {};
	}
}

function numberOr(value: unknown, fallback: number): number {
	return typeof value === "number" ? value : fallback;
}

function stringOr(value: unknown): string {
	return typeof value === "string" ? value : "";
}

export function readConfig(file: string): Config {
	const config = readJson(file);
	return {
		enabled: config.enabled === true,
		warnSeconds: numberOr(config.warnSeconds, DEFAULT_WARN_SECONDS),
		cookiePath: stringOr(config.cookiePath),
		domain: stringOr(config.domain),
		intervalSeconds: Math.max(MIN_INTERVAL_SECONDS, numberOr(config.intervalSeconds, DEFAULT_INTERVAL_SECONDS)),
	};
}

export function writeEnabledSetting(file: string, enabled: boolean): void {
	fs.writeFileSync(file, `${JSON.stringify({ ...readJson(file), enabled }, null, 2)}\n`);
}

export type CredentialCache = { file?: string; domain?: string; mtimeMs?: number; expiry?: number };

export function createCredentialCache(): CredentialCache {
	return {};
}

function expandHome(file: string): string {
	return file === "~" || file.startsWith("~/") ? path.join(os.homedir(), file.slice(1)) : file;
}

export function readExpiry(cache: CredentialCache, cookiePath: string, domain: string): number | undefined {
	const file = expandHome(cookiePath);
	let mtimeMs: number;
	try {
		mtimeMs = fs.statSync(file).mtimeMs;
	} catch {
		Object.assign(cache, createCredentialCache());
		return undefined;
	}
	if (cache.file === file && cache.domain === domain && cache.mtimeMs === mtimeMs) return cache.expiry;
	let expiry: number | undefined;
	try {
		expiry = parseExpiry(fs.readFileSync(file, "utf8"), domain);
	} catch {
		return undefined;
	}
	Object.assign(cache, { file, domain, mtimeMs, expiry });
	return expiry;
}

const STATUS_KEY = "credential-expiry";
const VARIABLE_EVENT = "zentui:variable";
const CAPABILITY_EVENT = "zentui:variable-capability";
const VARIABLE = "llm-prompts/credential-expiry:left";

type EventSource = Pick<ExtensionAPI, "events">;
type StatusUi = Pick<ExtensionContext["ui"], "setStatus">;

function variableActive({ events }: EventSource): boolean {
	const probe = { supported: false, active: false, key: VARIABLE };
	events.emit(CAPABILITY_EVENT, probe);
	return probe.active;
}

export function publish(pi: EventSource, ui: StatusUi, text: string): void {
	if (variableActive(pi)) {
		pi.events.emit(VARIABLE_EVENT, { key: VARIABLE, text });
		ui.setStatus(STATUS_KEY, undefined);
	} else {
		ui.setStatus(STATUS_KEY, text);
	}
}

export function clear(pi: EventSource, ui: StatusUi): void {
	pi.events.emit(VARIABLE_EVENT, { key: VARIABLE, text: undefined });
	ui.setStatus(STATUS_KEY, undefined);
}

export default function (pi: ExtensionAPI) {
	const configPath = path.join(getAgentDir(), CONFIG_FILE);
	const cache = createCredentialCache();
	let timer: ReturnType<typeof setInterval> | undefined;

	function currentText(config: Config): string {
		return formatRemaining(readExpiry(cache, config.cookiePath, config.domain), Date.now() / MS_PER_SECOND, config.warnSeconds);
	}

	function stopTimer(): void {
		clearInterval(timer);
		timer = undefined;
	}

	function startTimer(ctx: ExtensionContext): void {
		stopTimer();
		const config = readConfig(configPath);
		if (!config.cookiePath) return;
		const tick = (): void => publish(pi, ctx.ui, currentText(readConfig(configPath)));
		timer = setInterval(tick, config.intervalSeconds * MS_PER_SECOND);
		timer.unref();
		tick();
	}

	function setEnabled(ctx: ExtensionCommandContext, value: string): void {
		writeEnabledSetting(configPath, value === "on");
		if (value === "on") {
			startTimer(ctx);
			if (!readConfig(configPath).cookiePath) ctx.ui.notify("credential-expiry needs cookiePath in credential-expiry.json", "warning");
		} else {
			stopTimer();
			clear(pi, ctx.ui);
		}
		ctx.ui.notify(`credential-expiry ${value}`, "info");
	}

	pi.on("session_start", (_event, ctx) => {
		if (readConfig(configPath).enabled) startTimer(ctx);
	});
	pi.on("session_shutdown", (_event, ctx) => {
		stopTimer();
		clear(pi, ctx.ui);
	});
	pi.registerCommand("credential-expiry", {
		description: "Time left on the credential cookie. `on|off` toggles the status line.",
		handler: async (args, ctx) => {
			const word = args.trim();
			if (word === "on" || word === "off") return setEnabled(ctx, word);
			if (word) {
				ctx.ui.notify(USAGE, "warning");
				return;
			}
			ctx.ui.notify(currentText(readConfig(configPath)), "info");
		},
	});
}
