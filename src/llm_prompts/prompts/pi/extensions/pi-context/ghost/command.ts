// The /ghost command: saves the last run as a ghost and lists the repository's ghosts.
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { VERSION } from "@earendil-works/pi-coding-agent";
import { deriveCheck, findSecret, type Ghost, PARAM_VALUE, parameterize, READ_ONLY, type Step, stepsHash } from "./model.ts";
import type { Recorder } from "./recorder.ts";
import { currentRepo } from "./repo.ts";
import { ghostPath, listGhosts, NAME, readGhost, removeGhost, writeGhost } from "./store.ts";

const MAX_SHOWN = 200;
const USAGE = "Usage: /ghost save <name> [param=value ...] | /ghost list";

function parseParams(pairs: string[]): Record<string, string> {
	const params: Record<string, string> = {};
	for (const pair of pairs) {
		const [, name, value] = /^(\w+)=(.*)$/.exec(pair) ?? [];
		if (!name || !PARAM_VALUE.test(value)) throw new Error(`Give each parameter as name=value, using letters, digits and . _ / @ : + - only. Check parameter ${name ?? pair}.`);
		params[name] = value;
	}
	return params;
}

function fromRun(name: string, pairs: string[], repo: { key: string; branch: string }, recorder: Recorder): Ghost {
	const run = recorder.last();
	if (!run) throw new Error("Nothing to save: no run has finished in this session.");
	if (!run.clean) throw new Error("The last run cannot be saved: it was aborted, a call failed, it used a tool that cannot be replayed, or it has more than 50 steps.");
	const params = parseParams(pairs);
	const steps: Step[] = run.steps.map((step, index) => ({ ...step, check: deriveCheck(run.outputs[index], step.isError) }));
	return {
		version: 1,
		name,
		repoKey: repo.key,
		branch: repo.branch,
		piVersion: VERSION,
		params: Object.fromEntries(Object.entries(params).map(([key, value]) => [key, { default: value, pattern: PARAM_VALUE.source }])),
		steps: parameterize(steps, params, run.outputs),
	};
}

async function save(words: string[], ctx: ExtensionCommandContext, recorder: Recorder): Promise<string> {
	const [name = "", ...pairs] = words;
	if (!NAME.test(name)) throw new Error("Name the ghost with lowercase letters, digits and dashes, up to 40 characters.");
	const repo = await currentRepo(ctx.cwd);
	const draftFile = ghostPath(repo.key, name, true);
	const draft = await readGhost(draftFile);
	if (draft && pairs.length > 0) throw new Error(`The parameters are already in the draft ${draftFile}. Edit them there, or delete the draft to save the last run again.`);
	const ghost = draft ?? fromRun(name, pairs, repo, recorder);
	const defaults = { tool: "parameter defaults", args: Object.fromEntries(Object.entries(ghost.params).map(([key, param]) => [key, param.default])), check: null, isError: false };
	const secret = findSecret([...ghost.steps, defaults], process.env);
	if (secret) throw new Error(`Step ${secret.step} (${[...ghost.steps, defaults][secret.step - 1].tool}) matches the secret pattern ${secret.pattern}, so nothing was saved.`);
	const unchecked = ghost.steps.flatMap((step, index) => (step.check ? [] : [index + 1]));
	if (unchecked.length > 0) {
		if (!draft) await writeGhost(draftFile, ghost);
		const which = unchecked.length === 1 ? `Step ${unchecked[0]} has` : `Steps ${unchecked.join(", ")} have`;
		throw new Error(`${which} no check. Edit ${draftFile} to set each "check" (for example {"isError":false,"output":{"regex":"^ok$"}}), then run /ghost save ${name} again.`);
	}
	delete ghost.approvedHash;
	if (ghost.steps.some((step) => !READ_ONLY.has(step.tool))) {
		if (!ctx.hasUI) throw new Error("This ghost has steps that can change things, and saving it needs a prompt to approve them. Save it from an interactive session.");
		const shown = ghost.steps.map((step, index) => `${index + 1}. ${step.tool} ${JSON.stringify(step.args)}`.slice(0, MAX_SHOWN));
		if (!(await ctx.ui.confirm(`Save ghost ${name}? Replays will run these steps without asking again`, shown.join("\n")))) return "Not saved.";
		ghost.approvedHash = stepsHash(ghost.steps);
	}
	const file = ghostPath(repo.key, name);
	await writeGhost(file, ghost);
	await removeGhost(draftFile);
	return `Saved ghost ${name} (${ghost.steps.length} steps) to ${file}.`;
}

async function list(cwd: string): Promise<string> {
	const repo = await currentRepo(cwd);
	const lines = await Promise.all((await listGhosts(repo.key)).map(async (name) => `${name}: ${(await readGhost(ghostPath(repo.key, name)))?.steps.length} steps`));
	return lines.join("\n") || "No ghosts for this repository.";
}

export function registerGhostCommand(pi: ExtensionAPI, recorder: Recorder): void {
	pi.registerCommand("ghost", {
		description: "Save the last run as a replayable ghost (`save <name> [param=value ...]`), or list this repository's ghosts",
		handler: async (args: string, ctx: ExtensionCommandContext) => {
			const [verb, ...words] = args.trim().split(/\s+/);
			try {
				ctx.ui.notify(verb === "save" ? await save(words, ctx, recorder) : verb === "list" ? await list(ctx.cwd) : USAGE, "info");
			} catch (error) {
				ctx.ui.notify(error instanceof Error ? error.message : String(error), "warning");
			}
		},
	});
}
