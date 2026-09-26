import { lazy, Suspense } from "react";
import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { AutomationsSettingsPage } from "./SettingsPage";
import { manualCommands } from "./commands";
import { GRAPH_CANVAS_SLOT, type GraphCanvasProps } from "./canvas-contract";

const GraphCanvas = lazy(() => import("./GraphCanvas"));

/** Automations' UI (bundled with the host — a core plugin, RADD-1373): its settings page, the
 * manual-run commands on an issue, and the graph canvas as a slot (what the canvas browser proof
 * mounts on its own). */
export default definePlugin({ commandSources: [manualCommands], contributions: [
  { id: "settings", slot: SlotId.settingsPage, match: "/settings/automations", render: () => <AutomationsSettingsPage /> },
  {
    id: "graph-canvas", slot: GRAPH_CANVAS_SLOT, toggleable: false,
    render: (props) => (
      <Suspense fallback={<div className="h-[620px] border border-subtle p-4">Loading canvas…</div>}>
        <GraphCanvas {...(props as unknown as GraphCanvasProps)} />
      </Suspense>
    ),
  },
] });
