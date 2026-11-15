// Hides rarely used skills and tools behind one-line stubs and an unlock tool.
// Config: settings.json llmPrompts.attic.manifest (manifest path; default attic.json in pi's agent directory, where `llm-prompts attic build` writes it; no readable manifest means no effect)
import { readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { type ExtensionAPI, type ExtensionContext, getAgentDir } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Item = { kind: "skill" | "tool"; name: string; stub?: string };
type Entry = { type: string; customType?: string; data?: unknown };

const ENTRY_TYPE = "attic";
// Mirrors src/llm_prompts/attic/pinned.json.
const PINNED = new Set(["git-usage", "bash", "edit", "read", "unlock", "write"]);
const UNLOCK_TYPE = "attic-unlock";
const PARAMETERS = Type.Object({ name: Type.String({ description: "Name of a skill or tool listed in the attic section." }) });

function loadItems(pi: ExtensionAPI): Item[] | undefined {
	const settings = pi.getSettings() as { llmPrompts?: { attic?: { manifest?: string } } };
	try {
		return JSON.parse(readFileSync(settings.llmPrompts?.attic?.manifest ?? join(getAgentDir(), "attic.json"), "utf8")).items.filter((item: Item) => !PINNED.has(item.name)) as Item[];
	} catch {
		return undefined;
	}
}

const customData = <T>(branch: Entry[], type: string): T[] => branch.flatMap((entry) => (entry.type === "custom" && entry.customType === type ? [entry.data as T] : []));

export default function (pi: ExtensionAPI) {
	let items: Item[] | undefined;
	let stubs = new Map<string, string | undefined>();
	const hiddenSkills = new Map<string, string>();
	const hiddenTools = new Set<string>();
	const unlocked = new Set<string>();

	pi.on("session_start", () => {
		items = loadItems(pi);
		unlocked.clear();
		stubs = new Map(items?.map((item) => [item.name, item.stub]));
		if (!items) pi.setActiveTools(pi.getActiveTools().filter((name) => name !== "unlock"));
	});

	pi.on("before_agent_start", (event, ctx: ExtensionContext) => {
		const options = event.systemPromptOptions;
		if (!items) {
			options.selectedTools = options.selectedTools.filter((name) => name !== "unlock");
			return;
		}
		const listed = items;
		const branch = ctx.sessionManager.getBranch() as Entry[];
		const saved = customData<{ hidden: string[] }>(branch, ENTRY_TYPE).pop()?.hidden;
		const wanted = new Set(saved ?? listed.map((item) => item.name));
		const active = pi.getActiveTools();
		const skills = options.skills.filter((skill) => wanted.has(skill.name) && listed.some((item) => item.kind === "skill" && item.name === skill.name));
		const tools = (saved ?? active).filter((name) => listed.some((item) => item.kind === "tool" && item.name === name));
		const hidden = [...skills.map((skill) => skill.name), ...tools].sort();
		if (!saved) pi.appendEntry(ENTRY_TYPE, { hidden });
		for (const { name } of customData<{ name: string }>(branch, UNLOCK_TYPE)) unlocked.add(name);
		hiddenSkills.clear();
		for (const skill of skills) hiddenSkills.set(skill.name, skill.filePath);
		hiddenTools.clear();
		for (const name of tools) hiddenTools.add(name);
		const gone = new Set(tools.filter((name) => !unlocked.has(name)));
		options.skills = options.skills.filter((skill) => !hiddenSkills.has(skill.name));
		options.selectedTools = options.selectedTools.filter((name) => !gone.has(name));
		if (gone.size) pi.setActiveTools(active.filter((name) => !gone.has(name)));
		const stubLines = hidden.filter((name) => !unlocked.has(name) || hiddenSkills.has(name)).map((name) => `- ${name}${stubs.get(name) ? `: ${stubs.get(name)}` : ""}`);
		if (stubLines.length) options.sections.attic = `Rarely used skills and tools are hidden. Call unlock({name}) to use one.\n${stubLines.join("\n")}`;
	});

	pi.registerTool({
		name: "unlock",
		label: "Unlock",
		description: "Use a skill or tool listed in the attic section: returns a skill's file text, or makes a tool available.",
		promptSnippet: "Use a skill or tool hidden in the attic",
		parameters: PARAMETERS,
		async execute(_toolCallId, params) {
			const { name } = params;
			const path = hiddenSkills.get(name);
			if (path === undefined && !hiddenTools.has(name)) throw new Error(`"${name}" is not in the attic`);
			pi.appendEntry(UNLOCK_TYPE, { name });
			if (path !== undefined) return { content: [{ type: "text", text: `${path}\n\n${await readFile(path, "utf8")}` }], details: {} };
			unlocked.add(name);
			const active = pi.getActiveTools();
			if (!active.includes(name)) pi.setActiveTools([...active, name]);
			return { content: [{ type: "text", text: `${name} is now available.` }], details: {} };
		},
	});
}
