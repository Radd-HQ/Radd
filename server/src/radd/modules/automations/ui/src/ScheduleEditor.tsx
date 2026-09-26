import { api, ScheduleEditor, type ScheduleConfig, type SchedulePreview } from "@radd/plugin-sdk";

const previewSchedule = (value: ScheduleConfig, signal: AbortSignal) =>
  api.post<SchedulePreview>("/automations/schedule/preview", value, { signal });

export default function OwnedScheduleEditor(props: { value: ScheduleConfig; onChange: (schedule: ScheduleConfig) => void }) {
  return <div className="flex flex-col gap-2">
    <ScheduleEditor {...props} previewSchedule={previewSchedule} />
    <p className="text-xs text-fg-secondary">A schedule starts the graph once per occurrence. Add a Create issue action for recurring work, or a search node to select issues for other actions.</p>
  </div>;
}
