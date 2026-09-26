import { AutomationScope } from "./query-lifetime";
import { AutomationsSettingsPage } from "./SettingsPage";
import { manualCommands } from "./commands";
import { lazy, Suspense } from "react";
import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { GRAPH_CANVAS_SLOT, type GraphCanvasProps } from "./canvas-contract";

import ScheduleEditor from "./ScheduleEditor";
import { SCHEDULE_EDITOR_SLOT, type ScheduleEditorProps } from "./schedule-contract";

const GraphCanvas = lazy(() => import("./GraphCanvas"));
export default definePlugin({ commandSources: [manualCommands], contributions: [
  {id: "settings", slot: SlotId.settingsPage, match: "/settings/automations", render: () => <AutomationScope><AutomationsSettingsPage /></AutomationScope>},
{
  id: "graph-canvas", slot: GRAPH_CANVAS_SLOT, toggleable: false,
  render: props => <Suspense fallback={<div className="h-[620px] border border-subtle p-4">Loading canvas…</div>}>
    <GraphCanvas {...(props as unknown as GraphCanvasProps)} />
  </Suspense>,
}, {id: "schedule-editor", slot: SCHEDULE_EDITOR_SLOT, toggleable: false,
  render: props => <ScheduleEditor {...(props as unknown as ScheduleEditorProps)} />,
}] });
