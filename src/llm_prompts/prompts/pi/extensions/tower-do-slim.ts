// Re-registers the tower_do, tower_do_talk and tower_do_status tools with shorter descriptions, parameter schemas and guidelines, shortens the board reminder to counts, task keys and the tasks the board notes still in the context do not state, and on session start removes open tasks of owners with no board activity for 3 days.
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext, ExtensionToolContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { IDLE_FOLD_EVENT } from "./context-fold.ts";
import { foldBoard } from "./tower-do-patch.ts";

const REMINDER_TYPE = "pi-tower-do-reminder";
const REVISION_ENTRY_TYPE = "tower-do-noted-revisions";

type Slim = { description: string; promptGuidelines: string[] };
type TowerState = {
	formatTakeoverWindow(): string;
	MAX_TOWER_DO_OPEN_TASKS: number;
	TASK_KEY_PATTERN: RegExp;
	normalizeIdentity(identity: string, location: string): string;
	parseActivityLine(line: string): { by: string; at: number } | undefined;
};
type BoardModule = { TowerBoard: new (file: string) => { rawLines(): Promise<string[]> } };
type PathsModule = { boardFileFor(cwd: string): string; BoardCache: new () => { entryFor(cwd: string): { config: { identity?: string } } } };
type TowerModule = { default: (pi: ExtensionAPI) => void | Promise<void> };
type BoardTask = Awaited<ReturnType<typeof foldBoard>>["tasks"][number];

const DAY_MS = 24 * 60 * 60_000;
export const EXPIRE_IDLE_MS = 3 * DAY_MS;

/** Keys of unblocked open tasks idle for more than EXPIRE_IDLE_MS whose owner is not `caller` and wrote nothing to the board in that time, less any that a kept task still depends on, so one removal write passes the dependency check. */
export function expiredTaskKeys(tasks: BoardTask[], lastActive: ReadonlyMap<string, number>, caller: string, now: number): string[] {
	const idle = (at: number | undefined) => at === undefined || now - at > EXPIRE_IDLE_MS;
	const expired = new Set(
		tasks
			.filter((task) => task.owner && task.owner !== caller && !["completed", "blocked"].includes(task.status) && !task.blockedBy?.length && idle(task.updatedAt) && idle(lastActive.get(task.owner)))
			.map((task) => task.key),
	);
	for (let size = -1; size !== expired.size; ) {
		size = expired.size;
		for (const task of tasks) if (!expired.has(task.key)) for (const dependency of task.dependsOn ?? []) expired.delete(dependency);
	}
	return [...expired];
}

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
const UNLISTED_LINE = /^Not listed: \d+ open task\(s\) of others idle over 24h\.$/;
const LISTED_IDLE_MS = DAY_MS;

const listLine = (label: string, keys: string[]) => (keys.length ? `${label} ${keys.join(", ")}` : label);
const textOf = ({ content }: { content: string | { text?: string }[] }) => (typeof content === "string" ? content : content.map((part) => part.text ?? "").join(""));

/** Writes board notes and reads them back from the tool results a model can still see, so a note only repeats what no visible note states. */
export function boardNotes(taskKeyPattern: RegExp) {
	const key = taskKeyPattern.source.replace(/^\^|\$$/g, "");
	const taskLine = new RegExp(`^- \\[[a-z_]+\\] (${key}): `);
	const notedRevisions = new Map<string, string>();
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
			else if (UNLISTED_LINE.test(line)) continue;
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

	/** Rewrites a tower-do board reminder to counts and task keys, or to nothing for a revision already noted, with the full line only for tasks the notes in `messages` do not state.
	 * With `boardTasks`, it leaves out tasks of others idle over 24h and counts them instead. */
	const compactReminder = (text: string, messages: any[], boardTasks: BoardTask[] = [], now = Date.now()) => {
		const [header = "", ...rest] = text.split("\n");
		const match = REMINDER_HEADER.exec(header);
		if (!match) return text;
		const [, identity, revision, open, blocked, unread] = match;
		if (notedRevisions.get(identity) === revision) return;
		notedRevisions.set(identity, revision);
		const visible = visibleBoard(messages, identity);
		const known = visible ?? new Map<string, string>();
		const onBoard = new Map<string, string>();
		for (const line of rest) {
			const task = taskLine.exec(line)?.[1];
			if (task) onBoard.set(task, line);
			for (const hidden of OVERFLOW_LINE.exec(line)?.[1].split(", ") ?? []) onBoard.set(hidden, known.get(hidden) ?? "");
		}
		const unlisted = new Set(boardTasks.filter((task) => task.owner !== identity && now - task.updatedAt > LISTED_IDLE_MS && onBoard.has(task.key)).map((task) => task.key));
		const tasks = [...onBoard].filter(([task]) => !unlisted.has(task));
		const changed = tasks.filter(([task, line]) => line && known.get(task) !== line);
		const added = visible ? tasks.filter(([task, line]) => !line && !known.has(task)).map(([task]) => task) : [];
		const gone = [...known.keys()].filter((task) => !onBoard.has(task));
		return [
			`[board] revision ${revision}, you are ${identity}: ${open} open (${blocked} blocked), ${unread} unread. tower_do_status for details.`,
			...(changed.length ? [CHANGED_LABEL, ...changed.map(([, line]) => line)] : []),
			...(visible ? [] : [listLine(OPEN_LABEL, tasks.map(([task]) => task)), ...(unlisted.size ? [`Not listed: ${unlisted.size} open task(s) of others idle over 24h.`] : [])]),
			...(added.length ? [listLine(NEW_LABEL, added)] : []),
			...(gone.length ? [listLine(GONE_LABEL, gone)] : []),
		].join("\n");
	};
	return {
		compactReminder,
		notedRevisions: () => Object.fromEntries(notedRevisions),
		restoreRevisions: (saved: Record<string, string>) => {
			notedRevisions.clear();
			for (const [identity, revision] of Object.entries(saved)) notedRevisions.set(identity, revision);
		},
	};
}

const towerDir = () => join(getAgentDir(), "npm", "node_modules", "tower-do");
const loadFromTowerDo = <T>(file: string): Promise<T> => import(pathToFileURL(join(towerDir(), file)).href);

export default async function (pi: ExtensionAPI) {
	const towerState = await loadFromTowerDo<TowerState>("state.ts");
	const slim = slimTools(towerState);
	const { compactReminder, notedRevisions, restoreRevisions } = boardNotes(towerState.TASK_KEY_PATTERN);
	const { default: towerDo } = await loadFromTowerDo<TowerModule>("index.ts");
	const isChild = () => Boolean(process.env.PI_CONTEXT_CHILD || process.env.PI_SUBAGENT_CHILD);
	const towerTools: Record<string, ToolDefinition> = {};
	const registerTool = (tool: ToolDefinition) => {
		towerTools[tool.name] = tool;
		const override = slim[tool.name];
		pi.registerTool(override ? { ...tool, ...override, parameters: withoutDescriptions(tool.parameters) } : tool);
	};
	let pendingReminder: { text: string; messages: any[]; cwd?: string } | undefined;
	const detachReminder = (handler: Function) => async (event: any, ctx: any) => {
		const result = await handler(event, ctx);
		const messages: any[] | undefined = result?.messages;
		const last = messages?.at(-1);
		if (!messages || last?.customType !== REMINDER_TYPE) return result;
		pendingReminder = { text: textOf(last), messages, cwd: ctx?.cwd };
		return { ...result, messages: messages.slice(0, -1) };
	};
	const on = (event: string, handler: Function) => pi.on(event as never, (event === "context" ? detachReminder(handler) : handler) as never);
	pi.events.on(IDLE_FOLD_EVENT, (data) => {
		if (pendingReminder) pendingReminder.messages = (data as { messages: any[] }).messages;
	});
	pi.on("session_start", (_event, ctx) => {
		const saved = (ctx.sessionManager.getBranch() as { type: string; customType?: string; data?: Record<string, string> }[]).filter((entry) => entry.type === "custom" && entry.customType === REVISION_ENTRY_TYPE).at(-1);
		restoreRevisions(saved?.data ?? {});
	});
	pi.on("turn_end", () => {
		pendingReminder = undefined;
	});
	pi.on("tool_result", async (event) => {
		if (event.parentToolCallId || isChild() || pendingReminder === undefined) return;
		const { text: reminder, messages, cwd } = pendingReminder;
		pendingReminder = undefined;
		const tasks = cwd ? (await foldBoard(cwd).catch(() => undefined))?.tasks : undefined;
		const text = compactReminder(reminder, messages, tasks);
		if (text === undefined) return;
		pi.appendEntry(REVISION_ENTRY_TYPE, notedRevisions());
		return { content: [...event.content, { type: "text", text }], structuredContent: event.structuredContent };
	});
	const wrappers: Record<string, unknown> = { registerTool, on };
	await towerDo(new Proxy(pi, { get: (target, key) => (typeof key === "string" && key in wrappers ? wrappers[key] : Reflect.get(target, key)) }));
	const [{ TowerBoard }, { boardFileFor, BoardCache }] = await Promise.all([loadFromTowerDo<BoardModule>("board.ts"), loadFromTowerDo<PathsModule>("paths.ts")]);
	/** The identity tower-do gives this session: the configured one, else the session name, else the session id. */
	const callerIdentity = (cwd: string, ctx: ExtensionContext) => {
		const configured = new BoardCache().entryFor(cwd).config.identity?.trim();
		const name = pi.getSessionName()?.trim();
		const named = name ? (() => { try { return towerState.normalizeIdentity(name, "session name"); } catch { return undefined; } })() : undefined;
		return configured || named || ctx.sessionManager.getSessionId() || "main";
	};
	const callTool = (name: string, params: unknown, ctx: ExtensionContext) => Promise.resolve(towerTools[name]?.execute(`expire-idle-${name}`, params as never, undefined, undefined, ctx as ExtensionToolContext));
	const expireIdleTasks = async (ctx: ExtensionContext) => {
		const view = await foldBoard(ctx.cwd);
		const lastActive = new Map<string, number>();
		for (const line of await new TowerBoard(boardFileFor(ctx.cwd)).rawLines()) {
			const entry = towerState.parseActivityLine(line);
			if (entry && entry.at > (lastActive.get(entry.by) ?? 0)) lastActive.set(entry.by, entry.at);
		}
		const expired = new Set(expiredTaskKeys(view.tasks, lastActive, callerIdentity(ctx.cwd, ctx), Date.now()));
		if (!expired.size) return;
		const removed = view.tasks.filter((task) => expired.has(task.key));
		for (const owner of new Set(removed.map((task) => task.owner!))) {
			const body = removed.filter((task) => task.owner === owner).map((task) => `- ${task.key} [${task.status}]: ${task.subject ?? ""}`);
			await callTool("tower_do_talk", { as: "tower", action: "send", to: owner, subject: "Removing your idle board tasks", body: [`You wrote nothing to the board for ${EXPIRE_IDLE_MS / DAY_MS} days, so these open tasks are being removed. Re-create any you still need:`, ...body].join("\n") }, ctx);
		}
		await callTool("tower_do", { as: "tower", baseRevision: view.revision, tasks: [], remove: [...expired] }, ctx);
		ctx.ui.notify(`tower-do: removed open tasks of owners idle for ${EXPIRE_IDLE_MS / DAY_MS} days: ${[...expired].join(", ")}`, "info");
	};
	pi.on("session_start", async (event, ctx) => {
		if (isChild() || !["startup", "new"].includes(event.reason)) return;
		await expireIdleTasks(ctx).catch(() => undefined);
	});
}
