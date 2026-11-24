// Re-registers the tower_do, tower_do_talk and tower_do_status tools with shorter descriptions, parameter schemas and guidelines, and shortens the board reminder to counts, task keys and the tasks the board notes still in the context do not state.
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { IDLE_FOLD_EVENT } from "./context-fold.ts";

const REMINDER_TYPE = "pi-tower-do-reminder";

type Slim = { description: string; promptGuidelines: string[] };
type TowerState = { formatTakeoverWindow(): string; MAX_TOWER_DO_OPEN_TASKS: number; TASK_KEY_PATTERN: RegExp };
type TowerModule = { default: (pi: ExtensionAPI) => void | Promise<void> };

export function withoutDescriptions<T>(node: T): T {
	if (Array.isArray(node)) return node.map(withoutDescriptions) as T;
	if (typeof node !== "object" || node === null) return node;
	const copy: Record<string, unknown> = { ...(node as Record<string, unknown>) };
	if (typeof copy.description === "string") delete copy.description;
	for (const key of Object.keys(copy)) copy[key] = withoutDescriptions(copy[key]);
	return copy as T;
}

export function slimTools({ formatTakeoverWindow, MAX_TOWER_DO_OPEN_TASKS }: TowerState): Record<string, Slim> {
	return {
		tower_do: {
			description: `Shared task board, upsert. Send only the rows you create or change. A new key needs subject and status. Unlisted tasks stay as they are, so delete with \`remove\`. Only a task's owner or "tower" may change or remove it. A non-completed task idle ${formatTakeoverWindow()}+ may be adopted by setting owner to yourself in a write that changes nothing else. in_progress and completed need every dependsOn entry completed. Pass baseRevision from tower_do_status. At most ${MAX_TOWER_DO_OPEN_TASKS} non-completed tasks. Put long evidence in tower_do_talk, not description.`,
			promptGuidelines: [
				"Use tower_do for the shared plan, not a private todo list. Read tower_do_status first and pass its baseRevision.",
				"For a plan of 3+ steps, call tower_do with subject + status before substantive work.",
				"Claim a task by setting owner and in_progress together. Mark it completed only after verification. Use blocked with a blockedBy note otherwise.",
				"To change another agent's task, message its owner with tower_do_talk.",
				"Reconcile the board before your final response. Do not make no-op tower_do calls.",
			],
		},
		tower_do_talk: {
			description: `Messages on the shared board. action=send needs to, subject and body, taskKey is optional. \`to\` is "all", "tower", a task owner or a recently active peer, never yourself. action=inbox lists and acknowledges your messages (limit, all=true includes retired ones). Use tower_do_status to read without acknowledging.`,
			promptGuidelines: [
				"Use tower_do_talk to reach task owners instead of editing their tasks. Keep bodies brief and reference files by path.",
			],
		},
		tower_do_status: {
			description:
				"Read the shared board: tasks, messages to you, recent activity, the board file path and the revision to pass as baseRevision. Does not acknowledge messages. taskKey returns one task in full. Large output is cut from the head.",
			promptGuidelines: [
				"Use tower_do_status before starting work and before finishing it. Pass taskKey to read your own task, and read the full board" +
					" only to find or plan work. After a stale-revision rejection, re-read it for the new revision.",
				"Share the board file path with subagents so they read it directly and report back.",
			],
		},
	};
}

const REMINDER_HEADER = /^TowerDo shared board — you are (.+?) \(revision (\d+); \d+ task\(s\), (\d+) open(?:, \d+ completed hidden)?, (\d+) blocked, (\d+) unread message\(s\) for you\)\.$/;
const OVERFLOW_LINE = /^… and \d+ more open task\(s\): (.+)$/;
const NOTE_HEADER = /^\[board\] revision \d+, you are (.+?): \d+ open \(\d+ blocked\), \d+ unread\. tower_do_status for details\.$/;
const CHANGED_LABEL = "Changed since the last board note:";
const OPEN_LABEL = "Open tasks:";
const NEW_LABEL = "New:";
const GONE_LABEL = "Completed or removed:";

const listLine = (label: string, keys: string[]) => (keys.length ? `${label} ${keys.join(", ")}` : label);
const textOf = ({ content }: { content: string | { text?: string }[] }) => (typeof content === "string" ? content : content.map((part) => part.text ?? "").join(""));

/** Writes board notes and reads them back from the tool results a model can still see, so a note only repeats what no visible note states. */
export function boardNotes(taskKeyPattern: RegExp) {
	const key = taskKeyPattern.source.replace(/^\^|\$$/g, "");
	const taskLine = new RegExp(`^- \\[[a-z_]+\\] (${key}): `);
	const noteTaskLine = new RegExp(`${taskLine.source}.*$`);
	const listPattern = new RegExp(`^(${[OPEN_LABEL, NEW_LABEL, GONE_LABEL].join("|")})((?: ${key}(?:, ${key})*)?)$`);

	/** Reads a whole text part as a note of `identity`, or undefined when any line is not part of the note format. */
	const parseNote = (text: string, identity: string) => {
		const [header = "", ...rest] = text.split("\n");
		if (NOTE_HEADER.exec(header)?.[1] !== identity) return;
		const note = { open: undefined as string[] | undefined, lines: new Map<string, string>(), added: [] as string[], gone: [] as string[] };
		let afterLabel = false;
		for (const line of rest) {
			const list = listPattern.exec(line);
			const task = afterLabel ? noteTaskLine.exec(line) : null;
			if (line === CHANGED_LABEL) afterLabel = true;
			else if (task) note.lines.set(task[1], line);
			else if (list) {
				const keys = list[2] ? list[2].slice(1).split(", ") : [];
				if (list[1] === OPEN_LABEL) note.open = keys;
				else note[list[1] === NEW_LABEL ? "added" : "gone"] = keys;
			} else return;
		}
		return note;
	};

	/** The tasks the visible notes state, by key, with the last full line shown for each (empty when only the key was). */
	const visibleBoard = (messages: any[], identity: string) => {
		let board: Map<string, string> | undefined;
		for (const message of messages) {
			const last = message?.role === "toolResult" && Array.isArray(message.content) ? message.content.at(-1) : undefined;
			const note = last?.type === "text" && typeof last.text === "string" ? parseNote(last.text, identity) : undefined;
			if (!note || (!note.open && !board)) continue;
			if (note.open) board = new Map(note.open.map((open) => [open, ""]));
			for (const [task, line] of note.lines) board!.set(task, line);
			for (const task of note.added) board!.set(task, board!.get(task) ?? "");
			for (const task of note.gone) board!.delete(task);
		}
		return board;
	};

	/** Rewrites a tower-do board reminder to counts and task keys, with the full line only for tasks the notes in `messages` do not state. */
	const compactReminder = (text: string, messages: any[]) => {
		const [header = "", ...rest] = text.split("\n");
		const match = REMINDER_HEADER.exec(header);
		if (!match) return text;
		const [, identity, revision, open, blocked, unread] = match;
		const visible = visibleBoard(messages, identity);
		const known = visible ?? new Map<string, string>();
		const tasks = new Map<string, string>();
		for (const line of rest) {
			const task = taskLine.exec(line)?.[1];
			if (task) tasks.set(task, line);
			for (const hidden of OVERFLOW_LINE.exec(line)?.[1].split(", ") ?? []) tasks.set(hidden, known.get(hidden) ?? "");
		}
		const changed = [...tasks].filter(([task, line]) => line && known.get(task) !== line);
		const added = visible ? [...tasks].filter(([task, line]) => !line && !known.has(task)).map(([task]) => task) : [];
		const gone = [...known.keys()].filter((task) => !tasks.has(task));
		return [
			`[board] revision ${revision}, you are ${identity}: ${open} open (${blocked} blocked), ${unread} unread. tower_do_status for details.`,
			...(changed.length ? [CHANGED_LABEL, ...changed.map(([, line]) => line)] : []),
			...(visible ? [] : [listLine(OPEN_LABEL, [...tasks.keys()])]),
			...(added.length ? [listLine(NEW_LABEL, added)] : []),
			...(gone.length ? [listLine(GONE_LABEL, gone)] : []),
		].join("\n");
	};
	return { compactReminder };
}

const towerDir = () => join(getAgentDir(), "npm", "node_modules", "tower-do");
const loadFromTowerDo = <T>(file: string): Promise<T> => import(pathToFileURL(join(towerDir(), file)).href);

export default async function (pi: ExtensionAPI) {
	const towerState = await loadFromTowerDo<TowerState>("state.ts");
	const slim = slimTools(towerState);
	const { compactReminder } = boardNotes(towerState.TASK_KEY_PATTERN);
	const { default: towerDo } = await loadFromTowerDo<TowerModule>("index.ts");
	const registerTool = (tool: ToolDefinition) => {
		const override = slim[tool.name];
		pi.registerTool(override ? { ...tool, ...override, parameters: withoutDescriptions(tool.parameters) } : tool);
	};
	let pendingReminder: { text: string; messages: any[] } | undefined;
	const detachReminder = (handler: Function) => async (event: any, ctx: any) => {
		const result = await handler(event, ctx);
		const messages: any[] | undefined = result?.messages;
		const last = messages?.at(-1);
		if (!messages || last?.customType !== REMINDER_TYPE) return result;
		pendingReminder = { text: textOf(last), messages };
		return { ...result, messages: messages.slice(0, -1) };
	};
	const on = (event: string, handler: Function) => pi.on(event as never, (event === "context" ? detachReminder(handler) : handler) as never);
	pi.events.on(IDLE_FOLD_EVENT, (data) => {
		if (pendingReminder) pendingReminder.messages = (data as { messages: any[] }).messages;
	});
	pi.on("turn_end", () => {
		pendingReminder = undefined;
	});
	pi.on("tool_result", (event) => {
		if (event.parentToolCallId || pendingReminder === undefined) return;
		const text = compactReminder(pendingReminder.text, pendingReminder.messages);
		pendingReminder = undefined;
		return { content: [...event.content, { type: "text", text }], structuredContent: event.structuredContent };
	});
	const wrappers: Record<string, unknown> = { registerTool, on };
	await towerDo(new Proxy(pi, { get: (target, key) => (typeof key === "string" && key in wrappers ? wrappers[key] : Reflect.get(target, key)) }));
}
