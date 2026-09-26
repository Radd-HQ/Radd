import { definePlugin } from "@radd/plugin-sdk";
import ScheduleEditor from "./ScheduleEditor";
import { SCHEDULE_EDITOR_SLOT, type ScheduleEditorProps } from "./schedule-contract";
export default definePlugin({contributions: [{id: "schedule-editor", slot: SCHEDULE_EDITOR_SLOT, toggleable: false,
  render: props => <ScheduleEditor {...(props as unknown as ScheduleEditorProps)} />,
}]});
