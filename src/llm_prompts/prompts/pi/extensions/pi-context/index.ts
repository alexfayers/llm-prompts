// Restricts a delegated pi session to its role.
// Env: PI_CONTEXT_CHILD (path of the handshake JSON `{role, worktree?}`; set only in a delegated session)
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { childGuard } from "./roles.ts";

export default function (pi: ExtensionAPI) {
	const handshake = process.env.PI_CONTEXT_CHILD;
	if (handshake) pi.on("tool_call", childGuard(handshake));
}
