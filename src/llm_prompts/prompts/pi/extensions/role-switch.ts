// Spawns the listed role@model:effort names by switching the delegating agent's own model and thinking around delegate_agent, so the child inherits them.
// Config: agent-role-variants.json in the agent dir, written by llm-prompts.
import fs from "node:fs";
import path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

type Thinking = Parameters<ExtensionAPI["setThinkingLevel"]>[0];
type Variants = Record<string, Record<string, { model: string; efforts: Record<string, string> }>>;
type Target = { provider: string; id: string; thinking: Thinking };

const NAME = /^([^@:]+)@([^@:]+):([^@:]+)$/;

function readVariants(): Variants {
	try {
		return JSON.parse(fs.readFileSync(path.join(getAgentDir(), "agent-role-variants.json"), "utf8")) as Variants;
	} catch {
		return {};
	}
}

function own<T>(record: Record<string, T> | undefined, key: string): T | undefined {
	return record && Object.hasOwn(record, key) ? record[key] : undefined;
}

function variantNames(variants: Variants, roles: string[]): string[] {
	return roles.flatMap((role) =>
		Object.entries(own(variants, role) ?? {}).flatMap(([alias, { efforts }]) => Object.keys(efforts).map((effort) => `${role}@${alias}:${effort}`)),
	);
}

export default function (pi: ExtensionAPI) {
	const variants = readVariants();
	let saved: Target | undefined;
	let listed: Set<string> | undefined;

	const switchTo = async (ctx: ExtensionContext, target: Target): Promise<string | undefined> => {
		const name = `${target.provider}/${target.id}`;
		const model = ctx.modelRegistry.find(target.provider, target.id);
		try {
			if (!model || !(await pi.setModel(model))) return `${name} is not available`;
		} catch (error) {
			return `${name}: ${error instanceof Error ? error.message : String(error)}`;
		}
		if (ctx.model?.provider !== target.provider || ctx.model.id !== target.id) return `the switch to ${name} did not take effect`;
		pi.setThinkingLevel(target.thinking);
		return pi.getThinkingLevel() === target.thinking ? undefined : `${name} does not support thinking ${target.thinking}`;
	};

	const restore = async (ctx: ExtensionContext) => {
		if (!saved) return;
		const failure = await switchTo(ctx, saved);
		if (failure) ctx.ui.notify(`role-switch could not restore the model: ${failure}`, "error");
		else saved = undefined;
	};

	pi.on("session_start", () => {
		const definition = (
			pi.getAllTools().find((tool) => tool.name === "delegate_agent")?.parameters as { properties?: { definition?: { enum?: unknown } } } | undefined
		)?.properties?.definition;
		if (!Array.isArray(definition?.enum)) return;
		const names = definition.enum.filter((name): name is string => typeof name === "string");
		definition.enum = [...new Set([...names, ...variantNames(variants, names)])];
		listed = new Set(definition.enum as string[]);
	});

	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "delegate_agent") return;
		const input = event.input as { definition?: string };
		const requested = input.definition ?? "";
		if (own(variants, requested)) return { block: true, reason: `Spawn ${requested} as ${requested}@<model>:<effort>, listed in its description` };
		const match = NAME.exec(requested);
		if (!match || (listed && !listed.has(requested))) return;
		const [, role, alias, effort] = match;
		const variant = own(own(variants, role), alias);
		const thinking = own(variant?.efforts, effort) as Thinking | undefined;
		if (!variant || !thinking) return;
		input.definition = role;
		if (!saved && ctx.model) saved = { provider: ctx.model.provider, id: ctx.model.id, thinking: pi.getThinkingLevel() };
		const separator = variant.model.indexOf("/");
		const failure = await switchTo(ctx, { provider: variant.model.slice(0, separator), id: variant.model.slice(separator + 1), thinking });
		if (!failure) return;
		await restore(ctx);
		return { block: true, reason: `Could not spawn ${requested}: ${failure}` };
	});

	pi.on("tool_execution_end", async (event, ctx) => {
		if (event.toolName === "delegate_agent") await restore(ctx);
	});
	pi.on("agent_end", async (_event, ctx) => restore(ctx));
	pi.on("session_shutdown", async (_event, ctx) => restore(ctx));
}
