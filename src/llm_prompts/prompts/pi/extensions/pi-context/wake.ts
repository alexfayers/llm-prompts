// Decides which finished fork runs wake the main session, and builds the digest line of those that wait for its next turn.
import { projectResult } from "../outcome-codes.ts";
import type { Run } from "./registry.ts";

export type WakeReason = "blocked-on-user" | "failed" | "notify" | "invalid" | "error" | "lost" | "all-done";

const VALID_CODES = ["done", "blocked-on-user", "failed", "found-it"];
const MAX_DIGEST_CHARS = 500;

/** Why main must run now for this run, or undefined when its result can wait in the digest. `liveAfter` counts the other runs still live. */
export function wakeReason(run: Run, liveAfter: number): WakeReason | undefined {
	if (run.state === "cancelled") return undefined;
	if (run.state === "lost") return "lost";
	if (run.state === "blocked") return "blocked-on-user";
	if (run.state === "failed") return run.outcome === "failed" ? "failed" : "error";
	if (!run.outcome || !VALID_CODES.includes(run.outcome)) return "invalid";
	if (run.notify) return "notify";
	return liveAfter === 0 ? "all-done" : undefined;
}

/** One digest entry: the run, its code, the lines of its reply main keeps and its ref. */
export function digestLine(run: Run, text: string): string {
	const body = projectResult(text)
		.split("\n")
		.filter((line) => !line.startsWith("OUTCOME "))
		.join("\n")
		.slice(0, MAX_DIGEST_CHARS);
	return [`[fork ${run.name} ${run.outcome ?? run.state}]`, body, `ref ${run.ref}`].filter(Boolean).join(" ");
}

/** Holds the digest lines of finished runs until main reads them. */
export class Coalescer {
	private lines: string[] = [];

	add(run: Run, text: string) {
		this.lines.push(digestLine(run, text));
	}

	take(): string[] {
		return this.lines.splice(0);
	}
}
