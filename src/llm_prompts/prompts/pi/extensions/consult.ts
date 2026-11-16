// Adds the consult tool, which asks a tool-less expert one question with the evidence given, in a fresh context at the model's highest thinking level.
// Config: settings.json llmPrompts.consult.model (<provider>/<id> of the expert; default: the session's model)
import { getSupportedThinkingLevels } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const MAX_EVIDENCE_BYTES = 16_000;
const EXPERT_PROMPT =
	"You are an expert advisor. You see only the question and the evidence given, and you have no tools. Answer concisely and concretely. If the evidence is not enough, answer `need more evidence: <what>`.";
const PARAMETERS = Type.Object({
	question: Type.String({ description: "The question for the expert." }),
	evidence: Type.Array(Type.String(), { description: `Every excerpt the expert needs, at most ${MAX_EVIDENCE_BYTES} bytes in total. It cannot see the session.` }),
});

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "consult",
		label: "Consult",
		description: "Get a second opinion on one question from an expert in a fresh context at maximum thinking effort. It has no tools and sees only the question and the evidence you pass, so quote what it needs. It may answer `need more evidence: X`.",
		promptSnippet: "Get a fresh-context, max-effort second opinion on one question with evidence",
		parameters: PARAMETERS,
		async execute(_toolCallId, params, signal, _onUpdate, ctx) {
			const size = params.evidence.reduce((total, text) => total + Buffer.byteLength(text), 0);
			if (size > MAX_EVIDENCE_BYTES) throw new Error(`evidence is ${size} bytes, over the ${MAX_EVIDENCE_BYTES} limit`);
			const configured = (pi.getSettings() as { llmPrompts?: { consult?: { model?: string } } }).llmPrompts?.consult?.model;
			let model = ctx.model;
			if (configured) {
				const [provider, ...rest] = configured.split("/");
				if (!provider || !rest.length) throw new Error("llmPrompts.consult.model must be <provider>/<id>");
				model = ctx.modelRegistry.find(provider, rest.join("/"));
				if (!model) throw new Error(`${configured} is not available`);
			}
			if (!model) throw new Error("no model is selected");
			const highest = getSupportedThinkingLevels(model).at(-1);
			const reasoning = highest === "off" ? undefined : highest;
			const content = [params.question, ...params.evidence.map((text, index) => `Evidence ${index + 1}:\n${text}`)].join("\n\n");
			const answer = await ctx.modelRegistry.streamSimple(model, { systemPrompt: EXPERT_PROMPT, messages: [{ role: "user", content, timestamp: Date.now() }] }, { signal, reasoning }).result();
			if (answer.stopReason === "error" || answer.stopReason === "aborted") throw new Error(answer.errorMessage ?? `the expert call ${answer.stopReason}`);
			const text = answer.content.flatMap((block) => (block.type === "text" ? [block.text] : [])).join("");
			if (!text) throw new Error("the expert gave no answer");
			return { content: [{ type: "text", text }], details: { model: `${model.provider}/${model.id}`, reasoning, cost: answer.usage.cost?.total ?? 0 } };
		},
	});
}
