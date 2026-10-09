import fs from "node:fs";
import path from "node:path";
import { generateDiffString, getAgentDir, renderDiff } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { wrapTextWithAnsi } from "@earendil-works/pi-tui";

const PREVIEW_SLOT = Symbol.for("llm-prompts.permission-preview");
const LONG_PREVIEW_CHARS = 120;
const ELLIPSIS = "...";
const COMPACT_LAYOUT = ["npm", "node_modules", "pi-compact-tools", "extensions", "compact-tools-layout.ts"];
const RENDERER_UNAVAILABLE = "diff-preview: pi-compact-tools renderer unavailable, using built-in diff";
const SUMMARY_LINE = /^for '(.*)' (\(.*\))$/;

type Replacement = { oldText: string; newText: string };
type Span = Replacement & { start: number };

const toLF = (text: string): string => text.replace(/\r\n/g, "\n");

function summarize(file: string, diff: string, isNew = false): string {
	const count = (mark: string) => diff.split("\n").filter((line) => line.startsWith(mark)).length;
	return `for '${file}' (${isNew ? `new file, +${count("+")}` : `+${count("+")} -${count("-")}`})`;
}

function readCurrent(file: string): string | undefined | null {
	try {
		return fs.readFileSync(file, "utf8");
	} catch (error) {
		return (error as NodeJS.ErrnoException).code === "ENOENT" ? null : undefined;
	}
}

function replacementsOf(input: Record<string, unknown>): Replacement[] | undefined {
	const candidates = Array.isArray(input.edits) ? input.edits : [input];
	const isReplacement = (value: unknown): value is Replacement => {
		const { oldText, newText } = (value ?? {}) as Record<string, unknown>;
		return typeof oldText === "string" && typeof newText === "string";
	};
	return candidates.length > 0 && candidates.every(isReplacement) ? candidates : undefined;
}

function applyEdits(original: string, replacements: Replacement[]): string | undefined {
	const spans: Span[] = replacements.map(({ oldText, newText }) => ({
		oldText: toLF(oldText),
		newText: toLF(newText),
		start: original.indexOf(toLF(oldText)),
	}));
	const unique = (span: Span) => span.oldText !== "" && span.start >= 0 && original.indexOf(span.oldText, span.start + 1) < 0;
	if (!spans.every(unique)) return undefined;
	spans.sort((first, second) => first.start - second.start);
	if (spans.some((span, index) => index > 0 && spans[index - 1].start + spans[index - 1].oldText.length > span.start)) return undefined;
	return spans.reduceRight(
		(text, span) => text.slice(0, span.start) + span.newText + text.slice(span.start + span.oldText.length),
		original,
	);
}

export function formatEditDiff(input: Record<string, unknown>, cwd: string): string | undefined {
	const replacements = replacementsOf(input);
	if (typeof input.path !== "string" || !replacements) return undefined;
	const current = readCurrent(path.resolve(cwd, input.path));
	const original = current ? toLF(current) : undefined;
	const updated = original === undefined ? undefined : applyEdits(original, replacements);
	const diff =
		original !== undefined && updated !== undefined
			? generateDiffString(original, updated).diff
			: replacements.map(({ oldText, newText }) => generateDiffString(toLF(oldText), toLF(newText)).diff).join("\n");
	return `${summarize(input.path, diff)}\n${diff}`;
}

export function formatWriteDiff(input: Record<string, unknown>, cwd: string): string | undefined {
	if (typeof input.path !== "string" || typeof input.content !== "string") return undefined;
	const current = readCurrent(path.resolve(cwd, input.path));
	if (current === undefined) return undefined;
	const diff = generateDiffString(toLF(current ?? ""), toLF(input.content)).diff;
	return `${summarize(input.path, diff, current === null)}\n${diff}`;
}

type Formatter = (input: Record<string, unknown>) => string | undefined;
type Verdict = { kind: "defer" };
type Notifier = { notify(message: string, type: "warning"): void };
type Evidence = { label: string; text: string };
type AskDetails = {
	requestId: string;
	payload: {
		kind?: string;
		request: { toolName: string | null; value: string; requester: { agentName: string | null; forwarded: boolean } };
		evidence: Evidence[];
	};
};
type CodeDiffComponent = { render(width: number): string[] };
type CodeDiffRenderer = (patch: string, displayDiff: string, path: string, theme: unknown) => CodeDiffComponent | undefined;
type Content = { title: string; path: string; body: string; diff: boolean };
type Preview = Content & { input?: Evidence };
type PublishedPreview = { title: string; lines(width: number, theme: unknown): string[] };
type Authorize = (details: unknown) => Promise<Verdict>;
type PermissionsService = {
	registerToolInputFormatter: (tool: string, formatter: Formatter) => () => void;
	registerAuthorizer: (name: string, authorize: Authorize) => () => void;
};

const SERVICES_KEY = Symbol.for("@gotgenes/pi-permission-system:session-services");

function safely(format: Formatter): Formatter {
	return (input) => {
		try {
			return format(input);
		} catch {
			return undefined;
		}
	};
}

async function loadCompactRenderer(): Promise<CodeDiffRenderer> {
	const layout = (await import(path.join(getAgentDir(), ...COMPACT_LAYOUT))) as { renderCodeDiff?: CodeDiffRenderer };
	if (typeof layout.renderCodeDiff !== "function") throw new Error("renderCodeDiff is not exported");
	return layout.renderCodeDiff;
}

const isLong = (text: string): boolean => text.includes("\n") || text.length > LONG_PREVIEW_CHARS;

function headOf(text: string): string {
	const [first] = text.split("\n");
	return first.length > LONG_PREVIEW_CHARS ? first.slice(0, LONG_PREVIEW_CHARS - ELLIPSIS.length) + ELLIPSIS : first;
}

function textPreviewOf(details: AskDetails, origin: string): Preview | undefined {
	const { kind, request, evidence } = details.payload;
	const input = evidence.find((entry) => entry.label === (kind === "bash" ? "full command" : "input"));
	const body = input?.text ?? (kind === "bash" ? request.value : "");
	if (!isLong(body)) return undefined;
	return { input, title: `${request.toolName ?? "tool"}${origin}`, path: request.value, body, diff: false };
}

function previewOf(details: AskDetails): Preview | undefined {
	const { request, evidence } = details.payload;
	const origin = request.requester.forwarded ? ` from ${request.requester.agentName ?? "a subagent"}` : "";
	if (request.toolName !== "edit" && request.toolName !== "write") return textPreviewOf(details, origin);
	const input = evidence.find((entry) => entry.label === "input");
	if (!input) return undefined;
	const [first, ...rest] = input.text.split("\n");
	const summary = SUMMARY_LINE.exec(first);
	const file = summary?.[1] ?? request.value;
	const stats = summary ? ` ${summary[2]}` : "";
	return {
		input,
		title: `Diff for '${file}'${stats}${origin}`,
		path: file,
		body: summary ? rest.join("\n") : input.text,
		diff: true,
	};
}

function paintDiff(text: string): string {
	try {
		return renderDiff(text);
	} catch {
		return text;
	}
}

class DiffPane implements PublishedPreview {
	private wrapped: { width: number; theme: unknown; lines: string[] } | undefined;
	private component: { theme: unknown; render: CodeDiffComponent["render"] } | undefined;
	private renderer: CodeDiffRenderer | undefined;

	private readonly content: Content;
	private readonly onRendererFailure: () => void;

	constructor(content: Content, renderer: CodeDiffRenderer | undefined, onRendererFailure: () => void) {
		this.content = content;
		this.renderer = renderer;
		this.onRendererFailure = onRendererFailure;
	}

	get title(): string {
		return this.content.title;
	}

	private compactLines(width: number, theme: unknown): string[] | undefined {
		if (!this.content.diff || !this.renderer) return undefined;
		try {
			if (!this.component || this.component.theme !== theme) {
				const drawn = this.renderer("", this.content.body, this.content.path, theme);
				this.component = drawn && { theme, render: (at) => drawn.render(at) };
			}
			return this.component?.render(width);
		} catch {
			this.renderer = undefined;
			this.onRendererFailure();
			return undefined;
		}
	}

	lines(width: number, theme: unknown): string[] {
		if (!this.wrapped || this.wrapped.width !== width || this.wrapped.theme !== theme) {
			const lines =
				this.compactLines(width, theme) ??
				(this.content.diff ? paintDiff(this.content.body) : this.content.body)
					.split("\n")
					.flatMap((line) => wrapTextWithAnsi(line, width));
			this.wrapped = { width, theme, lines };
		}
		return this.wrapped.lines;
	}
}

export default function (pi: ExtensionAPI): void {
	let cwd = process.cwd();
	let ui: Notifier | undefined;
	const published = (): Map<string, PublishedPreview> => {
		const slots = globalThis as Record<symbol, unknown>;
		return (slots[PREVIEW_SLOT] ??= new Map<string, PublishedPreview>()) as Map<string, PublishedPreview>;
	};
	let loading: Promise<CodeDiffRenderer> | undefined;
	let warned = false;

	const warnRendererUnavailable = (): void => {
		if (warned) return;
		warned = true;
		ui?.notify(RENDERER_UNAVAILABLE, "warning");
	};

	const compactRenderer = async (): Promise<CodeDiffRenderer | undefined> => {
		try {
			return await (loading ??= loadCompactRenderer());
		} catch {
			warnRendererUnavailable();
			return undefined;
		}
	};

	const preview: Authorize = async (details) => {
		try {
			const target = ui ? previewOf(details as AskDetails) : undefined;
			if (target) {
				const { title, path: file, body, diff } = target;
				const renderer = diff ? await compactRenderer() : undefined;
				published().set((details as AskDetails).requestId, new DiffPane({ title, path: file, body, diff }, renderer, warnRendererUnavailable));
				if (target.input) target.input.text = diff ? target.input.text.split("\n")[0] : headOf(target.input.text);
			}
		} catch {
			// a malformed ask is left for the dialog alone
		}
		return { kind: "defer" };
	};

	const dismissAll = (): void => published().clear();

	pi.events.on("permissions:decision", (data) => published().delete((data as { requestId: string }).requestId));

	const disposers = new Map<PermissionsService, (() => void)[]>();

	pi.on("session_start", (_event, ctx) => {
		dismissAll();
		loading = undefined;
		warned = false;
		cwd = ctx.cwd;
		ui = ctx.mode === "tui" ? ctx.ui : undefined;
	});

	pi.events.on("permissions:ready", (data) => {
		const { sessionId } = data as { sessionId: string | null };
		const services = (globalThis as Record<symbol, unknown>)[SERVICES_KEY] as Map<string, PermissionsService> | undefined;
		const service = sessionId ? services?.get(sessionId) : undefined;
		if (!service || disposers.has(service)) return;
		const formatters: Record<string, Formatter> = {
			edit: (input) => formatEditDiff(input, cwd),
			write: (input) => formatWriteDiff(input, cwd),
		};
		disposers.set(service, []);
		try {
			disposers.get(service)?.push(service.registerAuthorizer("diff-preview", preview));
		} catch {
			// another extension already owns this authorizer name
		}
		for (const [tool, format] of Object.entries(formatters)) {
			try {
				disposers.get(service)?.push(service.registerToolInputFormatter(tool, safely(format)));
			} catch {
				// another extension already owns this tool's formatter
			}
		}
	});

	pi.on("session_shutdown", () => {
		dismissAll();
		ui = undefined;
		for (const dispose of [...disposers.values()].flat()) dispose();
		disposers.clear();
	});
}
