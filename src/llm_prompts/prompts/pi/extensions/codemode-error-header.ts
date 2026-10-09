import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const FAILED_HEADER = "Script failed";
const ERROR_MARKER = "Script error:";

type Block = { type: string; text?: string };

function firstErrorLine(content: Block[]): string | undefined {
	const lines = content.flatMap((block) => (block.type === "text" ? (block.text ?? "").split("\n") : []));
	const marker = lines.lastIndexOf(ERROR_MARKER);
	return marker < 0 ? undefined : lines.slice(marker + 1).find((line) => line.trim() !== "")?.trim();
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_result", (event) => {
		if (event.toolName !== "codemode" || !event.isError) return;
		const [header, ...rest] = event.content as Block[];
		const [title, ...headerRest] = (header?.text ?? "").split("\n");
		const error = firstErrorLine(event.content as Block[]);
		if (header?.type !== "text" || title !== FAILED_HEADER || !error) return;
		return { content: [{ ...header, text: [`${title}: ${error}`, ...headerRest].join("\n") }, ...rest] as typeof event.content };
	});
}
