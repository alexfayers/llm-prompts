// Adds the consult tool, which asks a stronger tool-less expert model one question with the evidence given.
// Env: PI_CONSULT_MODEL (<provider>/<id> of the expert; unset means no effect)
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
	const target = process.env.PI_CONSULT_MODEL;
	if (!target) return;

	pi.registerTool({
		name: "consult",
		label: "Consult",
		description: "Ask a stronger expert model one question. It has no tools and sees only the question and the evidence you pass, so quote what it needs. It may answer `need more evidence: X`.",
		promptSnippet: "Ask a stronger expert model one question with evidence",
		parameters: PARAMETERS,
		async execute(_toolCallId, params, signal, _onUpdate, ctx) {
			const [provider, ...rest] = target.split("/");
			const id = rest.join("/");
			if (!provider || !id) throw new Error("PI_CONSULT_MODEL must be <provider>/<id>");
			const size = params.evidence.reduce((total, text) => total + Buffer.byteLength(text), 0);
			if (size > MAX_EVIDENCE_BYTES) throw new Error(`evidence is ${size} bytes, over the ${MAX_EVIDENCE_BYTES} limit`);
			const model = ctx.modelRegistry.find(provider, id);
			if (!model) throw new Error(`${target} is not available`);
			const content = [params.question, ...params.evidence.map((text, index) => `Evidence ${index + 1}:\n${text}`)].join("\n\n");
			const answer = await ctx.modelRegistry.streamSimple(model, { systemPrompt: EXPERT_PROMPT, messages: [{ role: "user", content, timestamp: Date.now() }] }, { signal }).result();
			if (answer.stopReason === "error" || answer.stopReason === "aborted") throw new Error(answer.errorMessage ?? `the expert call ${answer.stopReason}`);
			const text = answer.content.flatMap((block) => (block.type === "text" ? [block.text] : [])).join("");
			if (!text) throw new Error("the expert gave no answer");
			return { content: [{ type: "text", text }], details: { model: target, cost: answer.usage.cost.total } };
		},
	});
}
