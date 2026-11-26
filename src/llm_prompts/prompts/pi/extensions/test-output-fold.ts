// Replaces the output of a test or build run with a short summary once a later tool call has acted on it, keeping the full text fetchable with result_fetch.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { HANDOFF_LINE } from "./result-cap.ts";

type Block = { type: string; id?: string; name?: string; text?: string };
type Message = { role: string; toolCallId?: string; content?: string | Block[]; isError?: boolean };
type Entry = { customType?: string; data?: { ref: string; text: string } };
type Projected = { sourceEntry: { id: string }; messages: Message[] };

const MIN_OUTPUT_CHARS = 1500;
const MAX_FAILURES = 10;
const MAX_ERROR_LINES = 8;
const LINE_CHARS = 200;
const COMMAND_CHARS = 80;
const RUNNER =
	/(?:^|[;&|(])\s*(?:\w+=\S*\s+)*(?:(?:uv\s+run|pnpm\s+exec|npx)\s+)?(?:just|make|tox|nox|pytest|python3?\s+-m\s+(?:pytest|unittest)|vitest|jest|tsc|mypy|ruff|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|build|lint|check|type-check)|cargo\s+(?:test|build|check|clippy)|go\s+(?:test|build|vet)|node\s+--test)(?=$|[\s;&|)])/;
const FAILURE_LINE = /^(?:FAILED|ERROR|FAIL|not ok|--- FAIL)\b/;
const ERROR_LINE = /^E\s|\berror\b|Error:|panicked/i;
const TALLY_LINE = /\b\d+ (?:passed|failed|tests?)\b/i;
const EXIT_CODE = /Command exited with code (\d+)\s*$/;

const blocks = (message: Message): Block[] => (Array.isArray(message.content) ? message.content : []);
const textOf = (message: Message): string => blocks(message).map((block) => block.text ?? "").join("");
const shorten = (line: string): string => line.trim().slice(0, LINE_CHARS);

function summarize(command: string, full: string, ref: string, isError: boolean): string {
	const lines = full.split("\n");
	const failures = lines.filter((line) => FAILURE_LINE.test(line));
	const errors = lines.filter((line) => ERROR_LINE.test(line) && !failures.includes(line));
	const tally = lines.filter((line) => TALLY_LINE.test(line)).at(-1);
	const exit = EXIT_CODE.exec(full)?.[1];
	const parts = [
		`${command.trim().slice(0, COMMAND_CHARS)} ${isError ? `failed${exit ? ` (exit ${exit})` : ""}` : "passed"}`,
		...failures.slice(0, MAX_FAILURES).map(shorten),
		...(failures.length > MAX_FAILURES ? [`... ${failures.length - MAX_FAILURES} more`] : []),
		...errors.slice(0, MAX_ERROR_LINES).map(shorten),
		...(tally ? [shorten(tally)] : []),
		`${full.length} chars, result_fetch({ref:"${ref}"}) resends the full output`,
	];
	return `[test run: ${parts.join("\n")}]`;
}

const usesTool = ({ messages }: Projected): boolean => messages.some((message) => message.role === "assistant" && blocks(message).some((block) => block.type === "toolCall"));

export default function (pi: ExtensionAPI) {
	const runs = new Map<string, string>();
	pi.on("tool_result", (event) => {
		const command = (event.input as { command?: unknown }).command;
		if (event.toolName === "bash" && typeof command === "string" && RUNNER.test(command)) runs.set(event.toolCallId, command);
	});
	pi.on("turn_end", (event, ctx) => {
		if (event.outcome !== "completed") return;
		const entries = event.context.contextEntries as unknown as Projected[];
		const branch = ctx.sessionManager.getBranch() as unknown as Entry[];
		const drafts: typeof event.entries = [];
		for (const [index, { sourceEntry, messages }] of entries.entries()) {
			const [message] = messages;
			const command = runs.get(message?.toolCallId ?? "");
			if (command === undefined || !entries.slice(index + 1).some(usesTool)) continue;
			runs.delete(message.toolCallId as string);
			const ref = `rc-${message.toolCallId}`;
			const stored = branch.find((entry) => entry.customType === "result-cap" && entry.data?.ref === ref)?.data;
			const full = stored?.text ?? textOf(message);
			if (full.length < MIN_OUTPUT_CHARS || HANDOFF_LINE.test(full)) continue;
			if (!stored) drafts.push({ type: "custom", customType: "result-cap", data: { ref, text: full } });
			drafts.push({ type: "context_edit", targetId: sourceEntry.id, replacement: { content: [{ type: "text", text: summarize(command, full, ref, Boolean(message.isError)) }] } });
		}
		return drafts.length ? { entries: [...event.entries, ...drafts] } : undefined;
	});
}
