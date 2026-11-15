// Decides which fork runs wake the main session, and builds their digest lines.
import { projectResult } from "../outcome-codes.ts";
import type { Run } from "./registry.ts";

export type WakeReason = "blocked-on-user" | "failed" | "notify" | "invalid" | "error" | "lost" | "finished";

const VALID_CODES = ["done", "blocked-on-user", "failed", "found-it"];
const MAX_DIGEST_CHARS = 500;

/** Why main must run now for this run, or undefined while it is live or was cancelled. */
export function wakeReason(run: Run): WakeReason | undefined {
	if (run.state === "cancelled" || run.state === "running" || run.state === "landing") return undefined;
	if (run.state === "lost") return "lost";
	if (run.state === "blocked") return "blocked-on-user";
	if (run.state === "failed") return run.outcome === "failed" ? "failed" : "error";
	if (!run.outcome || !VALID_CODES.includes(run.outcome)) return "invalid";
	if (run.notify) return "notify";
	return "finished";
}

const NEVER_CUT = /^(ASK:|DENIED: ")/;

/** One digest entry: the run, its code, the lines of its reply main keeps, a note and its ref. ASK and DENIED lines are never cut. */
export function digestLine(run: Run, text: string, note?: string): string {
	let room = MAX_DIGEST_CHARS;
	let cut = false;
	const kept: string[] = [];
	for (const line of projectResult(text).split("\n")) {
		if (line.startsWith("OUTCOME ")) continue;
		if (NEVER_CUT.test(line)) {
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

/** Holds the digest lines of finished runs until main reads them. */
export class Coalescer {
	private lines: string[] = [];

	add(run: Run, text: string, note?: string) {
		this.lines.push(digestLine(run, text, note));
	}

	take(): string[] {
		return this.lines.splice(0);
	}
}
