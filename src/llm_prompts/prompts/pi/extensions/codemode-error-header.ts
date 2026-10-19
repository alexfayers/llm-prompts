// Puts the first error line of a failed codemode script into the result header and makes reading a missing tool give undefined.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const FAILED_HEADER = "Script failed";
const ERROR_MARKER = "Script error:";

const OPTIONS_PREFIX = "// @options:";
const DIRECTIVE_PROLOGUE = /^(?:\s*(?:\/\/[^\n]*\n\s*)*(?:"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')[ \t]*;)*/;
const SHADOW_TOOLS = ';tools=new Proxy(tools,{get:(t,p)=>typeof p!=="string"||p in t?t[p]:void 0});';

type Block = { type: string; text?: string };

function shadowTools(code: string): string {
	const lines = code.split("\n");
	const bodyStart = lines[0].trimStart().startsWith(OPTIONS_PREFIX) ? lines[0].length + 1 : 0;
	const misplacedOptions = lines.slice(1).some((line) => line.trimStart().startsWith(OPTIONS_PREFIX));
	if (misplacedOptions || bodyStart >= code.length) return code;
	const insertAt = bodyStart + (DIRECTIVE_PROLOGUE.exec(code.slice(bodyStart))?.[0].length ?? 0);
	return code.slice(0, insertAt) + SHADOW_TOOLS + code.slice(insertAt);
}

function firstErrorLine(content: Block[]): string | undefined {
	const lines = content.flatMap((block) => (block.type === "text" ? (block.text ?? "").split("\n") : []));
	const marker = lines.lastIndexOf(ERROR_MARKER);
	return marker < 0 ? undefined : lines.slice(marker + 1).find((line) => line.trim() !== "")?.trim();
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", (event) => {
		if (event.toolName !== "codemode" || typeof event.input.code !== "string") return;
		event.input.code = shadowTools(event.input.code);
	});
	pi.on("tool_result", (event) => {
		if (event.toolName !== "codemode" || !event.isError) return;
		const [header, ...rest] = event.content as Block[];
		const [title, ...headerRest] = (header?.text ?? "").split("\n");
		const error = firstErrorLine(event.content as Block[]);
		if (header?.type !== "text" || title !== FAILED_HEADER || !error) return;
		return { content: [{ ...header, text: [`${title}: ${error}`, ...headerRest].join("\n") }, ...rest] as typeof event.content };
	});
}
