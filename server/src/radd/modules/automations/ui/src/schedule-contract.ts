import type { ScheduleConfig } from "@radd/plugin-sdk";
export interface ScheduleEditorProps {
  value: ScheduleConfig;
  onChange: (schedule: ScheduleConfig) => void;
}
