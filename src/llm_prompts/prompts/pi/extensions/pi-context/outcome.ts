// Reads a delegate's OUTCOME line and reduces its reply to what main needs to see.
const OUTCOME = /^OUTCOME (done|blocked-on-user|failed|found-it)( notify)? ref:\S+([ \t].*)?$/;
const KEPT_ANYWHERE = /^(ASK:|DENIED: ")/;
const MAX_FOUND_LINE = 200;

/** The OUTCOME line, every ASK and DENIED line, and for found-it a short answer line after it. A reply without a coded OUTCOME line is kept whole. */
export function projectResult(text: string): string {
	const lines = text.split("\n");
	const at = lines.findIndex((line) => OUTCOME.test(line));
	if (at < 0) return text;
	const foundAt = lines[at].includes(" found-it ") ? lines.findIndex((line, i) => i > at && line.trim()) : -1;
	return lines.filter((line, i) => i === at || KEPT_ANYWHERE.test(line) || (i === foundAt && line.length <= MAX_FOUND_LINE)).join("\n");
}

const OUTCOME_LINE = /^OUTCOME (\S+)( notify)? ref:(\S+)([ \t].*)?$/m;

/** The code, notify flag and ref of the first OUTCOME line in a reply, whatever the code word is. Text after the ref is ignored. */
export function parseOutcome(text: string): { code: string; notify: boolean; ref: string } | undefined {
	const match = OUTCOME_LINE.exec(text);
	return match ? { code: match[1], notify: Boolean(match[2]), ref: match[3] } : undefined;
}
