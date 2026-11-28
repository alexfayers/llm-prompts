// Adds the reply tool a delegate ends its work with, and nudges a delegate that stops without calling it once per prompt. Every session declares the tool, so a warm fork keeps the lead's tools and prompt cache.
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";
import { OUTCOME_CODES, parseOutcome } from "./outcome.ts";
import { recordMainTools } from "./registry.ts";

const replyParameters = Type.Object({
	outcome: Type.Union([Type.Literal("done"), Type.Literal("found-it"), Type.Literal("blocked-on-user"), Type.Literal("failed")]),
	ref: Type.String({ description: "Where the result is: a PR URL, commit, file or result ref. Empty when there is none" }),
	notify: Type.Optional(Type.Boolean({ description: "Wake the lead even when the outcome is done" })),
	verdict: Type.Optional(Type.Union([Type.Literal("CLEAN"), Type.Literal("FINDINGS")], { description: "A review's verdict" })),
	findings: Type.Optional(Type.Array(Type.Object({ severity: Type.String(), location: Type.String({ description: "file:line" }), text: Type.String() }))),
	asks: Type.Optional(Type.Array(Type.String(), { description: "Questions only the user can answer" })),
	denied: Type.Optional(Type.Array(Type.String(), { description: "The verbatim reason of each permission denial" })),
	text: Type.Optional(Type.String({ description: "The report" })),
});

export type Reply = Static<typeof replyParameters>;

const oneLine = (text: string) => text.replace(/\s*\n\s*/g, " ");

/** The reply as text in the OUTCOME format: the OUTCOME line, the verdict, one line per finding, ask and denial, then the report. */
export const replyText = ({ outcome, ref, notify, verdict, findings = [], asks = [], denied = [], text }: Reply): string =>
	[
		`OUTCOME ${outcome}${notify ? " notify" : ""} ref:${ref}`,
		verdict && `Verdict: ${verdict}`,
		...findings.map(({ severity, location, text }) => `- ${severity} ${location}: ${oneLine(text)}`),
		...asks.map((ask) => `ASK: ${oneLine(ask)}`),
		...denied.map((reason) => `DENIED: "${oneLine(reason)}"`),
		text,
	].filter(Boolean).join("\n");

const errorResult = (text: string) => ({ content: [{ type: "text" as const, text }], details: {}, isError: true });

const replyTool = defineTool({
	name: "reply",
	label: "Reply",
	description: "Delegates only: end your work and report to the lead.",
	parameters: replyParameters,
	async execute() {
		return errorResult("Only a delegate uses reply. Answer in text.");
	},
});

type Block = { type: string; text?: string };
const textOf = (content: Block[]) => content.flatMap((block) => (block.type === "text" && block.text ? [block.text] : [])).join("\n");

/** Registers reply: a delegate's call made alone ends its turn, and any other call returns an error result. A delegate whose last text holds a valid OUTCOME line is not nudged. */
export function registerReply(pi: ExtensionAPI, delegate: boolean): void {
	if (!delegate) {
		pi.registerTool(replyTool);
		return;
	}
	let replied = false;
	let nudged = false;
	let callsInMessage = 0;
	let outcomeInText = false;
	pi.registerTool({
		...replyTool,
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			recordMainTools(ctx);
			if (callsInMessage > 1) return errorResult("Call reply alone, in a message with no other tool calls.");
			return { content: [{ type: "text", text: "reply sent" }], details: params, terminate: true };
		},
	});
	pi.on("message_end", ({ message }) => {
		if (message.role !== "assistant") return;
		const content = message.content as Block[];
		callsInMessage = content.filter((block) => block.type === "toolCall").length;
		const text = textOf(content);
		if (text.trim()) outcomeInText = OUTCOME_CODES.includes(parseOutcome(text)?.code ?? "");
	});
	pi.on("tool_result", (event) => {
		if (event.toolName === "reply" && !event.isError) replied = true;
	});
	pi.on("agent_before_settle", (event) => {
		if (replied || outcomeInText || nudged || event.outcome !== "completed") return;
		nudged = true;
		return { entries: [...event.entries, { type: "custom_message", customType: "reply-nudge", content: "Call reply to end your work.", display: false }], continue: true };
	});
	pi.on("input", () => {
		replied = false;
		nudged = false;
		outcomeInText = false;
	});
}
