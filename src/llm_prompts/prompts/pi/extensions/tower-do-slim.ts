// Re-registers the tower_do, tower_do_talk and tower_do_status tools with shorter descriptions, parameter schemas and guidelines, and shortens the board reminder to counts, task keys and the tasks changed since the last reminder.
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";

const REMINDER_TYPE = "pi-tower-do-reminder";

type Slim = { description: string; promptGuidelines: string[] };
type TowerState = { formatTakeoverWindow(): string; MAX_TOWER_DO_OPEN_TASKS: number };
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
				"Use tower_do_status before starting work and before finishing it. After a stale-revision rejection, re-read it for the new revision.",
				"Share the board file path with subagents so they read it directly and report back.",
			],
		},
	};
}

const REMINDER_HEADER = /^TowerDo shared board — you are (.+?) \(revision (\d+); \d+ task\(s\), (\d+) open(?:, \d+ completed hidden)?, (\d+) blocked, (\d+) unread message\(s\) for you\)\.$/;
const TASK_LINE = /^- \[[^\]]+\] ([^:]+): /;
const OVERFLOW_LINE = /^… and \d+ more open task\(s\): (.+)$/;

/** Rewrites a tower-do board reminder to counts and task keys, with the full line only for tasks new or changed since the lines in `seen`, which it updates. */
export function compactReminder(text: string, seen: Map<string, string>): string {
	const [header = "", ...rest] = text.split("\n");
	const match = REMINDER_HEADER.exec(header);
	if (!match) return text;
	const [, identity, revision, open, blocked, unread] = match;
	const tasks = new Map<string, string>();
	for (const line of rest) {
		const key = TASK_LINE.exec(line)?.[1];
		if (key) tasks.set(key, line);
		for (const hidden of OVERFLOW_LINE.exec(line)?.[1].split(", ") ?? []) tasks.set(hidden, seen.get(hidden) ?? "");
	}
	const changed = [...tasks].filter(([key, line]) => line && seen.get(key) !== line);
	const others = [...tasks.keys()].filter((key) => !changed.some(([other]) => other === key));
	const gone = [...seen.keys()].filter((key) => !tasks.has(key));
	seen.clear();
	for (const [key, line] of tasks) seen.set(key, line);
	return [
		`[board] revision ${revision}, you are ${identity}: ${open} open (${blocked} blocked), ${unread} unread. tower_do_status for details.`,
		...(changed.length ? ["Changed since the last board note:", ...changed.map(([, line]) => line)] : []),
		...(others.length ? [`Other open: ${others.join(", ")}`] : []),
		...(gone.length ? [`Completed or removed: ${gone.join(", ")}`] : []),
	].join("\n");
}

const towerDir = () => join(getAgentDir(), "npm", "node_modules", "tower-do");
const loadFromTowerDo = <T>(file: string): Promise<T> => import(pathToFileURL(join(towerDir(), file)).href);

export default async function (pi: ExtensionAPI) {
	const slim = slimTools(await loadFromTowerDo<TowerState>("state.ts"));
	const { default: towerDo } = await loadFromTowerDo<TowerModule>("index.ts");
	const registerTool = (tool: ToolDefinition) => {
		const override = slim[tool.name];
		pi.registerTool(override ? { ...tool, ...override, parameters: withoutDescriptions(tool.parameters) } : tool);
	};
	let pendingReminder: string | undefined;
	const seenTasks = new Map<string, string>();
	let seenSession: string | undefined;
	const detachReminder = (handler: Function) => async (event: any, ctx: any) => {
		const result = await handler(event, ctx);
		const messages: any[] | undefined = result?.messages;
		const last = messages?.at(-1);
		if (!messages || last?.customType !== REMINDER_TYPE) return result;
		const session = ctx?.sessionManager?.getSessionId?.();
		if (session !== seenSession) seenTasks.clear();
		seenSession = session;
		pendingReminder = compactReminder(typeof last.content === "string" ? last.content : last.content.map((part: { text?: string }) => part.text ?? "").join(""), seenTasks);
		return { ...result, messages: messages.slice(0, -1) };
	};
	const on = (event: string, handler: Function) => pi.on(event as never, (event === "context" ? detachReminder(handler) : handler) as never);
	pi.on("turn_end", () => {
		pendingReminder = undefined;
	});
	pi.on("session_compact", () => seenTasks.clear());
	pi.on("session_tree", () => seenTasks.clear());
	pi.on("tool_result", (event) => {
		if (pendingReminder === undefined) return;
		const text = pendingReminder;
		pendingReminder = undefined;
		return { content: [...event.content, { type: "text", text }], structuredContent: event.structuredContent };
	});
	const wrappers: Record<string, unknown> = { registerTool, on };
	await towerDo(new Proxy(pi, { get: (target, key) => (typeof key === "string" && key in wrappers ? wrappers[key] : Reflect.get(target, key)) }));
}
