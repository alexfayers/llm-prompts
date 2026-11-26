// Runs delegated pi sessions as cache-sharing forks and workers, restricts a delegate to its role, gives a cold worker AGENTS.delegate.md in place of AGENTS.md, and records and replays ghosts.
// Commands: /ghost save <name> [param=value ...], /ghost list
// Env: PI_CONTEXT_CHILD (path of the handshake JSON `{role, worktree?, bridge?}`; set only in a delegated session)
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Background, registerBackgroundHooks } from "./background.ts";
import { readBridgeConfig, registerChildBridge, trackPrefix, useCacheKey, useLeadPrefix } from "./bridge.ts";
import { registerFork, sweepFinished } from "./fork.ts";
import { registerGhostCommand } from "./ghost/command.ts";
import { Recorder, registerRecorder } from "./ghost/recorder.ts";
import { registerGhostRun } from "./ghost/run.ts";
import { LiveView, registerLiveView } from "./live-view.ts";
import { registerReply } from "./reply.ts";
import { childGuard, readHandshake, registerDelegateRules } from "./roles.ts";

export default function (pi: ExtensionAPI) {
	const background = new Background(pi);
	background.view = new LiveView(undefined, (run) => background.received(run));
	const handshake = process.env.PI_CONTEXT_CHILD;
	if (handshake) {
		pi.on("tool_call", childGuard(handshake));
		const { role, inherited, cacheKey } = readHandshake(handshake) ?? {};
		registerReply(pi, Boolean(role));
		if (!inherited) registerDelegateRules(pi, role?.name ?? "writer");
		else useLeadPrefix(pi, handshake);
		if (cacheKey) useCacheKey(pi, cacheKey);
		const bridge = readBridgeConfig(handshake);
		if (bridge) registerChildBridge(pi, bridge);
	} else {
		registerReply(pi, false);
		const recorder = new Recorder();
		registerRecorder(pi, recorder);
		registerGhostCommand(pi, recorder);
		trackPrefix(pi);
		registerBackgroundHooks(pi, background);
		pi.on("session_start", () => sweepFinished());
	}
	registerGhostRun(pi);
	registerFork(pi, undefined, background);
	registerLiveView(pi, background.view);
}
