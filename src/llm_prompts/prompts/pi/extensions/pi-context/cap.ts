// Starts a fork's process inside a systemd user scope that caps its memory and CPU, with every process it starts.
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import os from "node:os";

/** Share of the host's memory one fork may use. */
export const MEMORY_MAX_SHARE = 0.25;
/** Share of the host's cores one fork may use. */
export const CPU_QUOTA_SHARE = 0.5;

export interface ForkLimits {
	/** A systemd `MemoryMax` value, such as `16G`. */
	memoryMax?: string;
	/** A systemd `CPUQuota` value, such as `400%`. */
	cpuQuota?: string;
}

/** Whether `systemd-run --user --scope` can start a process here. */
export const systemdScopeWorks = (): boolean => spawnSync("systemd-run", ["--user", "--scope", "--quiet", "true"], { stdio: "ignore" }).status === 0;

export interface CappedCommand {
	command: string[];
	/** Stops the whole scope, with any process left in it, once. Resolves at once where the command is not capped. */
	release: () => Promise<void>;
}

/** Runs `systemctl` with `args` and resolves with its exit status and stderr. */
export type SystemctlLauncher = (args: string[]) => Promise<{ status: number | null; stderr: string }>;

const launchSystemctl: SystemctlLauncher = (args) =>
	new Promise((resolve) => {
		const child = spawn("systemctl", args, { stdio: ["ignore", "ignore", "pipe"], detached: true });
		let stderr = "";
		child.stderr.on("data", (chunk) => (stderr += chunk));
		child.on("error", (error) => resolve({ status: null, stderr: error.message }));
		child.on("close", (status) => resolve({ status, stderr }));
		child.unref();
	});

const UNIT_GONE = /not loaded|not found|does not exist/i;

/** Stops a scope's unit, warning on any failure except that the unit is already gone. */
export async function stopUnit(unit: string, launch: SystemctlLauncher = launchSystemctl, log: (line: string) => void = console.warn): Promise<void> {
	const { status, stderr } = await launch(["--user", "stop", `${unit}.scope`]);
	if (status !== 0 && !UNIT_GONE.test(stderr)) log(`pi-context: could not stop ${unit}: ${stderr.trim()}`);
}

/** Returns a function that wraps a command in a named, capped scope, or leaves it as is where `probe` finds no scope support, and says so once. */
export function forkCapper(probe: () => boolean = systemdScopeWorks, log: (line: string) => void = console.warn, launch: SystemctlLauncher = launchSystemctl) {
	let supported: boolean | undefined;
	return (command: string[], { memoryMax = `${Math.floor(os.totalmem() * MEMORY_MAX_SHARE)}`, cpuQuota = `${Math.floor(os.availableParallelism() * CPU_QUOTA_SHARE * 100)}%` }: ForkLimits = {}): CappedCommand => {
		if (supported === undefined) {
			supported = probe();
			if (!supported) log("pi-context: systemd-run --user --scope is unavailable, so forks start without a memory or CPU cap");
		}
		if (!supported) return { command, release: async () => undefined };
		const unit = `pi-fork-${randomUUID()}`;
		let stopping: Promise<void> | undefined;
		return {
			command: ["systemd-run", "--user", "--scope", "--quiet", `--unit=${unit}`, "-p", `MemoryMax=${memoryMax}`, "-p", `CPUQuota=${cpuQuota}`, ...command],
			release: () => (stopping ??= stopUnit(unit, launch, log)),
		};
	};
}

export const capCommand = forkCapper();
