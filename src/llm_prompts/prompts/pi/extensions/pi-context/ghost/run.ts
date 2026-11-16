// The ghost_run tool: replays a saved ghost through the same tool calls, hooks and guards as any other call, and stops at the first step that does not behave as saved.
import { type ExtensionAPI, VERSION } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { type Check, checkResult, type Ghost, PARAM_VALUE, READ_ONLY, render, type Step, stepsHash } from "./model.ts";
import { currentRepo } from "./repo.ts";
import { ghostPath, listGhosts, NAME, readGhost } from "./store.ts";

const SHOWN_EACH_END = 1500;
const KEPT_LINE = /^(ASK|DENIED):/;
const minor = (version: string) => version.split(".").slice(0, 2).join(".");
const allowed = (pattern: string, value: string) => PARAM_VALUE.test(value) && new RegExp(pattern).test(value);

/** Cuts a long output to its first and last characters, keeping every ASK and DENIED line whole. */
export function cut(text: string): string {
	if (text.length <= 2 * SHOWN_EACH_END) return text;
	const [head, tail] = [text.slice(0, SHOWN_EACH_END), text.slice(-SHOWN_EACH_END)];
	const kept = text.split("\n").filter((line) => KEPT_LINE.test(line) && !(head + tail).includes(line));
	return [head, `[${text.length - 2 * SHOWN_EACH_END} characters omitted]`, ...kept, tail].join("\n");
}

const fill = (step: Step, vars: Record<string, string>) => render({ args: step.args, check: step.check }, vars) as { value: { args: Record<string, unknown>; check: Check } } | { missing: string };

/** The reason a ghost cannot start in this repository with these parameters, if any. */
function preflight(ghost: Ghost, repo: { key: string; branch: string }, tools: string[], vars: Record<string, string>, given: Record<string, string>): string | undefined {
	if (ghost.repoKey !== repo.key) return "it was saved in a different repository";
	if (!("branch" in ghost.params) && ghost.branch !== repo.branch) return `it was saved on branch ${ghost.branch} and this is ${repo.branch}`;
	if (minor(ghost.piVersion) !== minor(VERSION)) return `it was saved with pi version ${ghost.piVersion} and this is ${VERSION}`;
	const unavailable = ghost.steps.find((step) => !tools.includes(step.tool));
	if (unavailable) return `the tool ${unavailable.tool} is not available`;
	const unchecked = ghost.steps.findIndex((step) => !step.check);
	if (unchecked >= 0) return `step ${unchecked + 1} has no check`;
	const unknown = Object.keys(given).find((key) => !(key in ghost.params));
	if (unknown) return `there is no parameter ${unknown}`;
	const refused = Object.entries(ghost.params).find(([key, param]) => !allowed(param.pattern, vars[key]));
	if (refused) return `the value of parameter ${refused[0]} is not allowed`;
	if (ghost.steps.some((step) => !READ_ONLY.has(step.tool)) && ghost.approvedHash !== stepsHash(ghost.steps)) return "its steps were not approved as they are now, so save it again with /ghost save";
	for (const [index, step] of ghost.steps.entries()) {
		const filled = fill(step, { ...vars, ...Object.fromEntries(Array.from({ length: index }, (_, earlier) => [`step${earlier + 1}`, ""])) });
		if ("missing" in filled) return `step ${index + 1} uses {{${filled.missing}}}, which is not defined`;
	}
}

export function registerGhostRun(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "ghost_run",
		label: "Ghost run",
		description: "Replay a ghost, a sequence of this repository's tool calls saved earlier, without a model call per step. It stops at the first step whose result differs from the saved one and reports it. An unknown name lists the saved ghosts.",
		parameters: Type.Object({
			name: Type.String({ description: "The saved ghost to replay" }),
			params: Type.Optional(Type.Record(Type.String(), Type.String(), { description: "Values for the ghost's parameters, by name" })),
		}),
		executionMode: "sequential",
		async execute(_toolCallId, { name, params: given = {} }, signal, _onUpdate, ctx) {
			const repo = await currentRepo(ctx.cwd);
			const ghost = NAME.test(name) ? await readGhost(ghostPath(repo.key, name)) : undefined;
			if (!ghost) throw new Error(`No ghost named ${name} for this repository. Saved ghosts: ${(await listGhosts(repo.key)).join(", ") || "none"}.`);
			const vars = { ...Object.fromEntries(Object.entries(ghost.params).map(([key, param]) => [key, param.default])), ...given };
			const reason = preflight(ghost, repo, ctx.tools.map((tool) => tool.name), vars, given);
			if (reason) throw new Error(`ghost ${name} diverged at step 0 (preflight): ${reason}. No step ran.`);
			const done: string[] = [];
			const outputs: string[] = [];
			const stop = (index: number, what: string, more = "") => new Error(`ghost ${name} ${what} at step ${index + 1} of ${ghost.steps.length} (${ghost.steps[index].tool})${more}\nDone: ${done.join(", ") || "none"}`);
			for (const [index, step] of ghost.steps.entries()) {
				if (signal?.aborted) throw stop(index, "aborted");
				const filled = fill(step, { ...vars, ...Object.fromEntries(outputs.flatMap((output, earlier) => (PARAM_VALUE.test(output.trim()) ? [[`step${earlier + 1}`, output.trim()]] : []))) });
				if ("missing" in filled) throw stop(index, "diverged", `: the value of {{${filled.missing}}} is not allowed`);
				const outcome = await ctx.executeTool(step.tool, filled.value.args, { signal });
				if (signal?.aborted) throw stop(index, "aborted");
				const text = outcome.result.content.flatMap((part) => (part.type === "text" ? [part.text] : [])).join("\n");
				if (!checkResult(filled.value.check, text, outcome.isError)) {
					throw stop(index, "diverged", `: the result did not match the saved check\nArgs: ${JSON.stringify(filled.value.args)}\nExpected: ${JSON.stringify(filled.value.check)}\nActual${outcome.isError ? " (error)" : ""}:\n${cut(text)}`);
				}
				outputs.push(text);
				done.push(`${index + 1}. ${step.tool}`);
			}
			return { content: [{ type: "text", text: `ghost ${name} ok (${ghost.steps.length} steps)` }], details: { steps: ghost.steps.map((step) => ({ tool: step.tool })) } };
		},
	});
}
