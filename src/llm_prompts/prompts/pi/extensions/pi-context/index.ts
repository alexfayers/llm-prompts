// Runs delegated pi sessions as cache-sharing forks and workers, and restricts a delegate to its role.
// Env: PI_CONTEXT_CHILD (path of the handshake JSON `{role, worktree?, bridge?}`; set only in a delegated session), PI_CONTEXT_MCP_PROXY (1: forks use main's MCP servers)
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Background, registerBackgroundHooks } from "./background.ts";
import { readBridgeConfig, registerChildBridge, reportPrefixToFile, trackPrefix } from "./bridge.ts";
import { registerBtw } from "./btw.ts";
import { registerFork } from "./fork.ts";
import { LiveView, registerLiveView } from "./live-view.ts";
import { childGuard } from "./roles.ts";

export default function (pi: ExtensionAPI) {
	const background = new Background(pi);
	background.view = new LiveView();
	const handshake = process.env.PI_CONTEXT_CHILD;
	if (handshake) {
		pi.on("tool_call", childGuard(handshake));
		const bridge = readBridgeConfig(handshake);
		if (bridge) registerChildBridge(pi, bridge);
		else reportPrefixToFile(pi, handshake);
	} else {
		trackPrefix(pi);
		if (!process.env.PI_HERDSMAN_MAILBOX) registerBackgroundHooks(pi, background);
	}
	registerFork(pi, undefined, background);
	registerBtw(pi);
	registerLiveView(pi, background.view);
}
