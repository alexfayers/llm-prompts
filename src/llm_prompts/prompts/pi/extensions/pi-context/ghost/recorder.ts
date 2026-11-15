// Records the steps of the latest agent run so that it can be saved as a ghost.
import type { ExtensionAPI, ToolCallEvent, ToolResultEvent } from "@earendil-works/pi-coding-agent";
import type { Step } from "./model.ts";

export const MAX_STEPS = 50;
const MAX_OUTPUT = 4096;
/** Tools whose calls cannot be replayed: they delegate, ask the user, or fetch what only this session holds. */
export const UNREPLAYABLE = new Set(["fork", "fork_cancel", "ghost_run", "asks", "ask_user", "await_owner", "delegate_agent", "result_fetch"]);

export interface RecordedRun {
	steps: Step[];
	/** Each step's output text, cut to its first 4 KB. */
	outputs: string[];
	/** False when the run was aborted, a call failed, a call cannot be replayed, or it has too many steps. */
	clean: boolean;
}

export class Recorder {
	private ids: string[] = [];
	private steps: Step[] = [];
	private outputs: string[] = [];
	private nested = new Map<string, { tool: string; isError: boolean }>();
	private pending = new Set<string>();
	private failed = false;
	private frozen: RecordedRun | undefined;

	/** Starts a new run. */
	onInput(): void {
		this.ids = [];
		this.steps = [];
		this.outputs = [];
		this.nested.clear();
		this.pending.clear();
		this.failed = false;
	}

	onCall(event: Pick<ToolCallEvent, "toolCallId" | "toolName" | "input" | "parentToolCallId">): void {
		if (UNREPLAYABLE.has(event.toolName)) this.failed = true;
		if (event.parentToolCallId === undefined) {
			if (this.steps.length > MAX_STEPS) return void (this.failed = true);
			this.ids.push(event.toolCallId);
			this.steps.push({ tool: event.toolName, args: structuredClone(event.input), check: null, isError: false });
			this.outputs.push("");
		} else {
			const step = this.stepOf(event.parentToolCallId);
			if (step === undefined || this.steps[step].tool === "ghost_run") return;
			const nested = { tool: event.toolName, isError: false };
			(this.steps[step].nested ??= []).push(nested);
			this.nested.set(event.toolCallId, nested);
		}
		this.pending.add(event.toolCallId);
	}

	onResult(event: Pick<ToolResultEvent, "toolCallId" | "input" | "content" | "isError">): void {
		if (!this.pending.delete(event.toolCallId)) return;
		if (event.isError) this.failed = true;
		const nested = this.nested.get(event.toolCallId);
		if (nested) return void (nested.isError = event.isError);
		const index = this.ids.indexOf(event.toolCallId);
		this.steps[index].isError = event.isError;
		this.steps[index].args = structuredClone(event.input);
		this.outputs[index] = event.content.flatMap((part) => (part.type === "text" ? [part.text] : [])).join("\n").slice(0, MAX_OUTPUT);
	}

	/** Freezes the run as the latest one when it has steps, and starts a new run. */
	onSettled({ aborted }: { aborted: boolean }): void {
		if (this.steps.length > 0) this.frozen = { steps: this.steps, outputs: this.outputs, clean: !aborted && !this.failed && this.pending.size === 0 && this.steps.length <= MAX_STEPS };
		this.onInput();
	}

	last(): RecordedRun | undefined {
		return this.frozen;
	}

	private stepOf(callId: string): number | undefined {
		const index = this.ids.findIndex((id) => callId === id || callId.startsWith(`${id}/`));
		return index < 0 ? undefined : index;
	}
}

export function registerRecorder(pi: ExtensionAPI, recorder: Recorder): void {
	pi.on("input", (event) => void (event.streamingBehavior === undefined && recorder.onInput()));
	pi.on("tool_call", (event) => void recorder.onCall(event));
	pi.on("tool_result", (event) => void recorder.onResult(event));
	pi.on("agent_settled", (event) => void recorder.onSettled(event));
}
