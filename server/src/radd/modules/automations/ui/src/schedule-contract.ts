import type { ScheduleConfig } from "@radd/plugin-sdk";
export const SCHEDULE_EDITOR_SLOT = "automations.schedule.editor";
export interface ScheduleEditorProps {
  value: ScheduleConfig;
  onChange: (schedule: ScheduleConfig) => void;
}
