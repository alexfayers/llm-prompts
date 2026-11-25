// Usage: node run-with-timeout.mjs <seconds> <command> [args...]
// Runs the command in its own process group and kills the whole group when the time runs out, a signal arrives or the command exits.
// A watchdog holds a pipe from this process and kills the group when the pipe closes, so the group also dies when this process is killed without a signal.
import { spawn } from "node:child_process";
import { constants } from "node:os";

const TIMED_OUT_EXIT_CODE = 124;
const KILL_GRACE_MS = 5_000;
const [seconds, command, ...args] = process.argv.slice(2);

const child = spawn(command, args, { stdio: "inherit", detached: true });
const killGroup = (signal) => {
	try {
		process.kill(-child.pid, signal);
	} catch {
		// the group is already gone
	}
};
const stopGroup = () => {
	killGroup("SIGTERM");
	setTimeout(() => killGroup("SIGKILL"), KILL_GRACE_MS).unref();
};

const watchdog = spawn("sh", ["-c", 'cat > /dev/null; kill -s KILL -- "-$0"', String(child.pid)], { stdio: ["pipe", "ignore", "ignore"], detached: true });
watchdog.on("error", () => {});
watchdog.stdin.on("error", () => {});

let timedOut = false;
const timer = setTimeout(() => {
	timedOut = true;
	console.error(`run-with-timeout: ${command} still running after ${seconds}s, stopping it`);
	stopGroup();
}, Number(seconds) * 1000);
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(signal, stopGroup);

child.on("error", (error) => {
	console.error(`run-with-timeout: ${error.message}`);
	process.exit(1);
});
child.on("exit", (code, signal) => {
	clearTimeout(timer);
	watchdog.kill();
	killGroup("SIGKILL");
	process.exit(timedOut ? TIMED_OUT_EXIT_CODE : (code ?? 128 + constants.signals[signal]));
});
