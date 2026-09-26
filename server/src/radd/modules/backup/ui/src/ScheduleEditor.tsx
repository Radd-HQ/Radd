import { api, ScheduleEditor, type ScheduleConfig, type SchedulePreview } from "@radd/plugin-sdk";
import type { ScheduleEditorProps } from "./schedule-contract";

const previewSchedule = (value: ScheduleConfig, signal: AbortSignal) =>
  api.post<SchedulePreview>("/backups/schedule/preview", value, { signal });

export default function OwnedScheduleEditor(props: ScheduleEditorProps) {
  return <div className="flex flex-col gap-2">
    <ScheduleEditor {...props} previewSchedule={previewSchedule} />
    <p className="text-xs text-fg-secondary">Each occurrence creates a backup using this schedule’s attachment and retention settings.</p>
  </div>;
}
