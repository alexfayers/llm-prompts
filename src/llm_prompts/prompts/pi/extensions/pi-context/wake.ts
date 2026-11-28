// Decides which fork runs wake the main session, and builds their digest lines.
import { MAX_BODY_CHARS, OUTCOME_CODES, projectReply } from "./outcome.ts";
import type { Run } from "./registry.ts";
import { replyText, type Reply } from "./reply.ts";

export type WakeReason = "blocked-on-user" | "failed" | "notify" | "invalid" | "error" | "lost" | "finished";

/** Why main must run now for this run, or undefined while it is live or was cancelled. */
export function wakeReason(run: Run): WakeReason | undefined {
	if (run.state === "cancelled" || run.state === "running" || run.state === "landing") return undefined;
	if (run.state === "lost") return "lost";
	if (run.state === "blocked") return "blocked-on-user";
	if (run.state === "failed") return run.outcome === "failed" ? "failed" : "error";
	if (!run.outcome || !OUTCOME_CODES.includes(run.outcome)) return "invalid";
	if (run.notify) return "notify";
	return "finished";
}

const NEVER_CUT = /^(ASK:|DENIED: ")/;

/** The lines of a reply main may keep, each marked whole when it is never cut: a reply call's verdict, findings, asks and denials, then its report quoted, or a text reply's ASK and DENIED lines. */
function digestParts(reply: string | Reply): { lines: { line: string; whole: boolean }[]; cut: boolean } {
	if (typeof reply !== "string") {
		const fields = replyText({ ...reply, text: undefined }).split("\n").slice(1).map((line) => ({ line, whole: true }));
		const body = (reply.text ?? "").split("\n").filter((line) => line.trim()).map((line) => ({ line: `> ${line}`, whole: false }));
		return { lines: [...fields, ...body], cut: false };
	}
	const projected = projectReply(reply);
	const lines = projected.text.split("\n").filter((line) => !line.startsWith("OUTCOME ")).map((line) => ({ line, whole: NEVER_CUT.test(line) }));
	return { lines, cut: projected.cut };
}

/** One digest entry: the run, its code, the lines of its reply main keeps, a note and its ref. */
export function digestLine(run: Run, reply: string | Reply, note?: string): string {
	let room = MAX_BODY_CHARS;
	const parts = digestParts(reply);
	let cut = parts.cut;
	const kept: string[] = [];
	for (const { line, whole } of parts.lines) {
		if (whole) {
			kept.push(line);
			continue;
		}
		cut ||= line.length > room;
		if (room > 0) kept.push(line.slice(0, room));
		room -= line.length + 1;
	}
	if (cut) kept.push(`… (cut${run.ref ? `, result_fetch ${run.ref}` : ""})`);
	return [`[fork ${run.name} ${run.outcome ?? run.state}]`, kept.join("\n"), note, run.ref && `ref ${run.ref}`].filter(Boolean).join(" ");
}
