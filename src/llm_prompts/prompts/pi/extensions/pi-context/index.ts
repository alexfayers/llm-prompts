// Runs delegated pi sessions as cache-sharing forks and workers, restricts a delegate to its role, and gives a cold worker AGENTS.delegate.md in place of AGENTS.md.
// Env: PI_CONTEXT_CHILD (path of the handshake JSON `{role, worktree?, bridge?}`; set only in a delegated session)
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Background, registerBackgroundHooks } from "./background.ts";
import { readBridgeConfig, registerChildBridge, reportPrefixToFile, trackPrefix } from "./bridge.ts";
import { registerBtw } from "./btw.ts";
import { registerFork, sweepFinished } from "./fork.ts";
import { LiveView, registerLiveView } from "./live-view.ts";
import { childGuard, readHandshake, registerDelegateRules } from "./roles.ts";

export default function (pi: ExtensionAPI) {
	const background = new Background(pi);
	background.view = new LiveView();
	const handshake = process.env.PI_CONTEXT_CHILD;
	if (handshake) {
		pi.on("tool_call", childGuard(handshake));
		if (!readHandshake(handshake)?.inherited) registerDelegateRules(pi);
		const bridge = readBridgeConfig(handshake);
		if (bridge) registerChildBridge(pi, bridge);
		else reportPrefixToFile(pi, handshake);
	} else {
		trackPrefix(pi);
		registerBackgroundHooks(pi, background);
		pi.on("session_start", () => sweepFinished());
	}
	registerFork(pi, undefined, background);
	registerBtw(pi);
	registerLiveView(pi, background.view);
}
