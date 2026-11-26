// Reads a delegate's OUTCOME line and reduces its reply to what main needs to see.
// An OUTCOME line may open with an emoji or other symbols, never words.
const LEAD = String.raw`^(?:[^\p{L}\p{N}\n]|[\p{L}\p{N}](?=[\uFE0F\u20E3]))*`;
export const OUTCOME_CODES = ["done", "blocked-on-user", "failed", "found-it"];
const OUTCOME = new RegExp(`${LEAD}OUTCOME (${OUTCOME_CODES.join("|")})( notify)? ref:(?:\\S+([ \\t].*)?|[ \\t]*)$`, "u");
const KEPT_ANYWHERE = /^(ASK:|DENIED: ")/;
export const MAX_BODY_CHARS = 600;

/** The OUTCOME line, every ASK and DENIED line, and the first `MAX_BODY_CHARS` characters of the other non-blank lines after the OUTCOME line, with whether any of those characters were dropped. A reply without a coded OUTCOME line is kept whole. */
export function projectReply(text: string): { text: string; cut: boolean } {
	const lines = text.split("\n");
	const at = lines.findIndex((line) => OUTCOME.test(line));
	if (at < 0) return { text, cut: false };
	let room = MAX_BODY_CHARS;
	let cut = false;
	const kept = lines.flatMap((line, i) => {
		if (i === at || KEPT_ANYWHERE.test(line)) return [line];
		if (i < at || !line.trim()) return [];
		cut ||= line.length > room;
		const body = room > 0 ? [line.slice(0, room)] : [];
		room -= line.length + 1;
		return body;
	});
	return { text: kept.join("\n"), cut };
}

export const projectResult = (text: string): string => projectReply(text).text;

const OUTCOME_LINE = new RegExp(`${LEAD}OUTCOME (\\S+)( notify)? ref:(?:(\\S+)([ \\t].*)?|[ \\t]*)$`, "mu");

/** The code, notify flag and ref of the first OUTCOME line in a reply, whatever the code word is. Text after the ref is ignored. */
export function parseOutcome(text: string): { code: string; notify: boolean; ref: string } | undefined {
	const match = OUTCOME_LINE.exec(text);
	return match ? { code: match[1], notify: Boolean(match[2]), ref: match[3] ?? "" } : undefined;
}
