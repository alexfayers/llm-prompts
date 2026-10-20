// Defines waitUntil(check, { intervalMs, timeoutMs }) at the top of each codemode script; it polls check with tools.sleep until check returns a truthy value.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { prependToScript } from "./codemode-error-header.ts";

const MAX_SLEEP_MS = 600_000;
const WAIT_UNTIL =
	"globalThis.waitUntil=async(check,{intervalMs=1000,timeoutMs=600000}={})=>{const end=Date.now()+timeoutMs;" +
	"for(;;){const left=end-Date.now();const value=await check();if(value)return value;" +
	"if(left<=0)throw new Error(`waitUntil timed out after ${timeoutMs} ms`);" +
	`await tools.sleep({ms:Math.min(intervalMs,left,${MAX_SLEEP_MS})});}};`;

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", (event) => {
		if (event.toolName !== "codemode" || typeof event.input.code !== "string") return;
		event.input.code = prependToScript(event.input.code, WAIT_UNTIL);
	});
}
