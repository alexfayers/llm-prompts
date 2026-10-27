// Re-registers the tower_do, tower_do_talk and tower_do_status tools with shorter descriptions, parameter schemas and guidelines.
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";

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

const towerDir = () => join(getAgentDir(), "npm", "node_modules", "tower-do");
const loadFromTowerDo = <T>(file: string): Promise<T> => import(pathToFileURL(join(towerDir(), file)).href);

export default async function (pi: ExtensionAPI) {
	const slim = slimTools(await loadFromTowerDo<TowerState>("state.ts"));
	const { default: towerDo } = await loadFromTowerDo<TowerModule>("index.ts");
	const registerTool = (tool: ToolDefinition) => {
		const override = slim[tool.name];
		pi.registerTool(override ? { ...tool, ...override, parameters: withoutDescriptions(tool.parameters) } : tool);
	};
	await towerDo(new Proxy(pi, { get: (target, key) => (key === "registerTool" ? registerTool : Reflect.get(target, key)) }));
}
