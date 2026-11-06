// Hides the tower-do widget above the editor by default and toggles it per session.
// Commands: /tower-widget
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const WIDGET_KEY = "pi-tower-do-widget";

type Ui = ExtensionContext["ui"];
type SetWidgetArgs = Parameters<Ui["setWidget"]>;

export default function (pi: ExtensionAPI) {
	let hidden = true;
	let latest: SetWidgetArgs | undefined;
	let patched: Ui | undefined;
	let original: Ui["setWidget"] | undefined;

	const show = () => original?.(...(latest ?? ([WIDGET_KEY, undefined] as unknown as SetWidgetArgs)));

	const patch = (ui: Ui) => {
		if (patched === ui) return;
		patched = ui;
		original = ui.setWidget.bind(ui) as Ui["setWidget"];
		ui.setWidget = ((...args: SetWidgetArgs) => {
			if (args[0] !== WIDGET_KEY) return original!(...args);
			latest = args[1] === undefined ? undefined : args;
			if (!hidden) return original!(...args);
			original!(WIDGET_KEY, undefined);
		}) as Ui["setWidget"];
		if (hidden) original(WIDGET_KEY, undefined);
	};

	pi.on("session_start", (_event, ctx) => {
		if (ctx.hasUI) patch(ctx.ui);
	});

	pi.registerCommand("tower-widget", {
		description: "Show or hide the tower-do widget above the editor",
		handler: async (_args, ctx) => {
			if (!ctx.hasUI) return;
			patch(ctx.ui);
			hidden = !hidden;
			if (hidden) original!(WIDGET_KEY, undefined);
			else show();
			ctx.ui.notify(`tower-do widget ${hidden ? "hidden" : "shown"}`, "info");
		},
	});
}
