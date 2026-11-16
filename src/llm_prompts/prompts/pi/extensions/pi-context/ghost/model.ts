// Ghost model: the recorded steps of a run, their checks and parameters, as pure functions.
import { createHash } from "node:crypto";

export type Check = { isError: boolean; output?: { exact: string } | { regex: string } | { empty: true } };

export interface Step {
	tool: string;
	args: Record<string, unknown>;
	check: Check | null;
	isError: boolean;
	/** The calls this step made itself, for display only. */
	nested?: { tool: string; isError: boolean }[];
}

export interface Ghost {
	version: 1;
	name: string;
	repoKey: string;
	branch: string;
	piVersion: string;
	params: Record<string, { default: string; pattern: string }>;
	steps: Step[];
	approvedHash?: string;
}

/** Tools whose calls only read, so a ghost made of them needs no approval. */
export const READ_ONLY = new Set(["read", "grep", "find", "ls", "lsp_diagnostics"]);
/** What a parameter value may be, so that it cannot carry shell syntax. */
export const PARAM_VALUE = /^[A-Za-z0-9._/@:+-]{1,200}$/;
const PLACEHOLDER = /\{\{(\w+)\}\}/g;
const MIN_REFERENCE_LENGTH = 6;

function mapStrings(value: unknown, change: (text: string) => string): unknown {
	if (typeof value === "string") return change(value);
	if (Array.isArray(value)) return value.map((item) => mapStrings(item, change));
	if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, mapStrings(item, change)]));
	return value;
}

/** Replaces each parameter value, and each earlier step's single-line output, in the steps' arguments and expected output with `{{name}}` or `{{stepN}}`. */
export function parameterize(steps: Step[], params: Record<string, string>, outputs: string[] = []): Step[] {
	return steps.map((step, index) => {
		const swaps: [string, string][] = Object.entries(params).map(([name, value]) => [value, name]);
		outputs.slice(0, index).forEach((output, earlier) => {
			const text = output.trim();
			if (text.length >= MIN_REFERENCE_LENGTH && !text.includes("\n")) swaps.push([text, `step${earlier + 1}`]);
		});
		swaps.sort(([a], [b]) => b.length - a.length);
		const swap = (text: string) => swaps.reduce((result, [value, name]) => (value ? result.replace(new RegExp(`(?<!\\w)${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?!\\w)`, "g"), `{{${name}}}`) : result), text);
		const exact = step.check?.output && "exact" in step.check.output ? step.check.output.exact : undefined;
		const check = exact === undefined ? step.check : { ...step.check!, output: { exact: swap(exact) } };
		return { ...step, args: mapStrings(step.args, swap) as Step["args"], check };
	});
}

/** Fills the `{{name}}` placeholders in every string of the value, or names the first variable that is missing. */
export function render(value: unknown, vars: Record<string, string>): { value: unknown } | { missing: string } {
	let missing: string | undefined;
	const filled = mapStrings(value, (text) => text.replace(PLACEHOLDER, (_, name: string) => vars[name] ?? ((missing ??= name), "")));
	return missing === undefined ? { value: filled } : { missing };
}

const MAX_EXACT_LINES = 5;
const MAX_EXACT_CHARS = 1000;
const VOLATILE = [/\b[0-9a-f]{7,40}\b/, /\d{4}-\d\d-\d\d|\d\d:\d\d:\d\d|\b\d{10,}\b/, /\/tmp\//];

/** Derives the check a result is expected to pass again: empty, or exact when short and stable, else none. */
export function deriveCheck(text: string, isError: boolean): Check | null {
	const output = text.trim();
	if (output === "") return { isError, output: { empty: true } };
	const stable = output.length <= MAX_EXACT_CHARS && output.split("\n").length <= MAX_EXACT_LINES && !VOLATILE.some((pattern) => pattern.test(output));
	return stable ? { isError, output: { exact: output } } : null;
}

/** Tells whether a result's error flag and trimmed text satisfy the check. */
export function checkResult(check: Check, text: string, isError: boolean): boolean {
	if (check.isError !== isError) return false;
	const expected = check.output;
	const output = text.trim();
	if (!expected) return true;
	if ("empty" in expected) return output === "";
	if ("exact" in expected) return output === expected.exact.trim();
	try {
		return new RegExp(expected.regex).test(output);
	} catch {
		return false;
	}
}

const canonical = (value: unknown): unknown =>
	Array.isArray(value) ? value.map(canonical) : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => (a < b ? -1 : 1)).map(([key, item]) => [key, canonical(item)])) : value;

/** Hashes the steps independently of key order. */
export const stepsHash = (steps: Step[]) => createHash("sha256").update(JSON.stringify(canonical(steps))).digest("hex");

const SECRET_PATTERNS: [string, RegExp][] = [
	["aws-access-key", /AKIA[0-9A-Z]{16}/],
	["private-key", /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
	["github-token", /gh[pousr]_\w{16,}|github_pat_\w{16,}/],
	["slack-token", /xox[abprs]-\w+/],
	["bearer-token", /Bearer \S{16,}/],
	["assigned-secret", /(TOKEN|SECRET|PASSWORD|API_KEY)=\S+/],
	["credential-path", /\.aws\/credentials|\.netrc|\/\.env|id_rsa/],
];
const SECRET_ENV_NAME = /TOKEN|SECRET|PASSWORD|KEY|CREDENTIAL/;
const MIN_SECRET_LENGTH = 8;

/** Finds the first step whose arguments or expected output hold a secret, naming the pattern and never the value. */
export function findSecret(steps: Step[], env: Record<string, string | undefined>): { step: number; pattern: string } | undefined {
	const secrets = Object.entries(env).filter((entry): entry is [string, string] => SECRET_ENV_NAME.test(entry[0]) && (entry[1]?.length ?? 0) >= MIN_SECRET_LENGTH);
	for (const [index, step] of steps.entries()) {
		const texts: string[] = [];
		mapStrings(step.args, (text) => (texts.push(text), text));
		const output = step.check?.output;
		if (output && "exact" in output) texts.push(output.exact);
		if (output && "regex" in output) texts.push(output.regex);
		const text = texts.join("\n");
		const pattern = SECRET_PATTERNS.find(([, regex]) => regex.test(text))?.[0] ?? secrets.map(([name]) => name).filter((name) => text.includes(env[name]!)).map((name) => `env:${name}`)[0];
		if (pattern) return { step: index + 1, pattern };
	}
}
