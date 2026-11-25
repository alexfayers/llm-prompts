// Runs a pi child in rpc mode and drives it one prompt at a time.
import { type ChildProcess, spawn } from "node:child_process";
import { capCommand, type CappedCommand, type ForkLimits } from "./cap.ts";

export interface Usage {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
}

export interface Turn {
	text: string;
	/** Usage summed over every request of the turn. */
	usage: Usage;
	/** Usage of the turn's first request. */
	firstUsage?: Usage;
	error?: string;
}

export interface UiRequest {
	id: string;
	method: string;
	[field: string]: unknown;
}

export interface UiAnswer {
	value?: string;
	confirmed?: boolean;
	cancelled?: boolean;
}

export interface RpcChildOptions {
	args: string[];
	cwd: string;
	env?: NodeJS.ProcessEnv;
	/** Executable and leading arguments that start pi; defaults to the running pi. */
	command?: string[];
	/** Starts the child in a capped systemd scope with these limits, where one is available. */
	limits?: ForkLimits;
	/** Wraps the command in a capped scope; defaults to a systemd user scope. */
	cap?: (command: string[], limits: ForkLimits) => CappedCommand;
	/** Aborts the running turn and closes the child. */
	signal?: AbortSignal;
	/** Receives the child's extension UI requests; a dialog it answers with nothing is cancelled. */
	onUi?: (request: UiRequest) => UiAnswer | undefined | Promise<UiAnswer | undefined>;
}

const DIALOG_METHODS = new Set(["select", "confirm", "input", "editor"]);

type Message = Record<string, any>;

const zeroUsage = (): Usage => ({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0 });

function pickUsage(raw: Message | undefined): Usage {
	const usage = zeroUsage();
	for (const key of Object.keys(usage) as (keyof Usage)[]) usage[key] = Number(raw?.[key]) || 0;
	return usage;
}

function addUsage(total: Usage, usage: Usage): void {
	for (const key of Object.keys(total) as (keyof Usage)[]) total[key] += usage[key];
}

export interface Exit {
	code: number | null;
	signal: NodeJS.Signals | null;
	/** Why the child ended, for an end the caller did not ask for. */
	reason?: string;
}

const STDERR_TAIL = 500;
const CLOSE_GRACE_MS = 5000;
const live = new Set<RpcChild>();
let exitHookInstalled = false;

function killLiveChildren(): void {
	for (const child of live) child.kill();
}
const failedTurn = (error: string): Turn => ({ text: "", usage: zeroUsage(), error });

export class RpcChild {
	/** Resolves once the child has ended; never rejects. */
	readonly exited: Promise<Exit>;
	private readonly child: ChildProcess;
	private readonly releaseScope: (() => Promise<void>) | undefined;
	private readonly onUi: RpcChildOptions["onUi"];
	private readonly replies = new Map<string, (record: Message) => void>();
	private buffer = "";
	private stderrTail = "";
	private nextId = 0;
	private ended: Exit | undefined;
	private busy = false;
	private onRecord: ((record: Message) => void) | undefined;
	private watchers = new Set<(record: Message) => void>();

	private constructor(options: RpcChildOptions) {
		this.onUi = options.onUi;
		const argv = [...(options.command ?? [process.execPath, process.argv[1] ?? "pi"]), ...options.args];
		const capped = options.limits ? (options.cap ?? capCommand)(argv, options.limits) : undefined;
		this.releaseScope = capped?.release;
		const [executable, ...args] = capped?.command ?? argv;
		this.child = spawn(executable, args, {
			cwd: options.cwd,
			env: options.env ?? process.env,
			stdio: ["pipe", "pipe", "pipe"],
		});
		this.exited = new Promise((resolve) => {
			let spawnError: string | undefined;
			this.child.on("error", (error) => {
				spawnError = error.message;
				this.end(resolve, { code: null, signal: null, reason: error.message });
			});
			this.child.once("close", (code, signal) => this.end(resolve, { code, signal, reason: spawnError }));
		});
		this.child.stdout?.setEncoding("utf8");
		this.child.stdout?.on("data", (chunk: string) => this.read(chunk));
		this.child.stderr?.setEncoding("utf8");
		this.child.stderr?.on("data", (chunk: string) => {
			this.stderrTail = (this.stderrTail + chunk).slice(-STDERR_TAIL);
		});
		live.add(this);
		if (!exitHookInstalled) {
			exitHookInstalled = true;
			process.once("exit", killLiveChildren);
		}
		void this.exited.then(() => live.delete(this));
		this.child.once("exit", () => void this.releaseScope?.());
		if (options.signal?.aborted) this.stop();
		else options.signal?.addEventListener("abort", () => this.stop(), { once: true });
		for (const stream of [this.child.stdin, this.child.stdout, this.child.stderr]) stream?.on("error", () => undefined);
	}

	static start(options: RpcChildOptions): RpcChild {
		return new RpcChild(options);
	}

	async prompt(text: string): Promise<Turn> {
		if (this.busy) return failedTurn("a prompt is already running");
		this.busy = true;
		try {
			return await this.runPrompt(text);
		} finally {
			this.busy = false;
			this.onRecord = undefined;
		}
	}

	get pid(): number | undefined {
		return this.child.pid;
	}

	/** Calls `listener` with every event record the child streams, and returns a function that stops it. */
	watch(listener: (record: Message) => void): () => void {
		this.watchers.add(listener);
		return () => void this.watchers.delete(listener);
	}

	abort(): void {
		this.send({ type: "abort" });
	}

	/** Queues a steering message for the running prompt, and returns why the child refused it, if it did. */
	async steer(text: string): Promise<string | undefined> {
		if (!this.busy) return "it is not running a prompt";
		const reply = await this.request({ type: "steer", message: text });
		return reply.success ? undefined : (reply.error ?? this.endReason());
	}

	/** Closes the child's input, terminates it once `graceMs` pass without an exit, and kills it after another `graceMs`. */
	close(graceMs = CLOSE_GRACE_MS): Promise<Exit> {
		this.child.stdin?.end();
		const timers = [setTimeout(() => this.kill(), graceMs), setTimeout(() => this.child.kill("SIGKILL"), graceMs * 2)];
		for (const timer of timers) timer.unref();
		return this.exited.finally(() => timers.forEach(clearTimeout)).then(async (exit) => (await this.releaseScope?.(), exit));
	}

	kill(): void {
		this.child.kill("SIGTERM");
		void this.releaseScope?.();
	}

	private stop(): void {
		this.abort();
		void this.close();
	}

	private async runPrompt(text: string): Promise<Turn> {
		const usage = zeroUsage();
		let firstUsage: Usage | undefined;
		let aborted = false;
		const settled = new Promise<void>((resolve) => {
			this.onRecord = (record) => {
				if (record.type === "message_end" && record.message?.role === "assistant") {
					const requestUsage = pickUsage(record.message.usage);
					firstUsage ??= requestUsage;
					addUsage(usage, requestUsage);
				} else if (record.type === "agent_settled") {
					aborted = Boolean(record.aborted);
					resolve();
				}
			};
		});
		const accepted = await this.request({ type: "prompt", message: text });
		if (!accepted.success) return failedTurn(accepted.error ?? this.endReason());
		if (accepted.data?.disposition === "handled") return { text: "", usage };
		await Promise.race([settled, this.exited]);
		if (this.ended) return failedTurn(this.endReason());
		const last = await this.request({ type: "get_last_assistant_text" });
		return { text: last.data?.text ?? "", usage, firstUsage, error: aborted ? "aborted" : undefined };
	}

	private end(resolve: (exit: Exit) => void, exit: Exit): void {
		if (this.ended) return;
		this.ended = exit;
		for (const reply of this.replies.values()) reply({ success: false, error: this.endReason() });
		this.replies.clear();
		resolve(exit);
	}

	private endReason(): string {
		const { code, signal, reason } = this.ended ?? {};
		const how = reason ?? `child exited (code ${code}${signal ? `, signal ${signal}` : ""})`;
		return this.stderrTail ? `${how}: ${this.stderrTail.trim()}` : how;
	}

	private async relay(request: UiRequest): Promise<void> {
		let answer: UiAnswer | undefined;
		try {
			answer = await this.onUi?.(request);
		} catch {
			answer = undefined;
		}
		if (DIALOG_METHODS.has(request.method)) this.send({ type: "extension_ui_response", id: request.id, ...(answer ?? { cancelled: true }) });
	}

	private send(command: Message): void {
		if (!this.ended) this.child.stdin?.write(`${JSON.stringify(command)}\n`);
	}

	private request(command: Message): Promise<Message> {
		if (this.ended) return Promise.resolve({ success: false, error: this.endReason() });
		const id = `r${this.nextId++}`;
		return new Promise((resolve) => {
			this.replies.set(id, resolve);
			this.send({ ...command, id });
		});
	}

	private read(chunk: string): void {
		this.buffer += chunk;
		for (let at = this.buffer.indexOf("\n"); at >= 0; at = this.buffer.indexOf("\n")) {
			const line = this.buffer.slice(0, at).replace(/\r$/, "");
			this.buffer = this.buffer.slice(at + 1);
			this.handle(line);
		}
	}

	private handle(line: string): void {
		let record: Message;
		try {
			record = JSON.parse(line);
		} catch {
			return;
		}
		if (record.type === "extension_ui_request") {
			void this.relay(record as UiRequest);
			return;
		}
		const reply = record.type === "response" ? this.replies.get(record.id) : undefined;
		if (reply) {
			this.replies.delete(record.id);
			reply(record);
		} else {
			this.onRecord?.(record);
			for (const watcher of this.watchers) watcher(record);
		}
	}
}
