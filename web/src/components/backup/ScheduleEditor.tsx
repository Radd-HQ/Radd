/** The host's typed entry to the Backup schedule editor; Backup owns its UI and requests. */
import { Slot } from "@radd/plugin-sdk";
import { SCHEDULE_EDITOR_SLOT, type ScheduleEditorProps } from "@radd-plugin-ui/backup/schedule-contract";
export function ScheduleEditor(props: ScheduleEditorProps) {
  const unavailable = <p role="status" className="text-xs text-fg-secondary">Schedule editor unavailable. Your schedule is preserved.</p>;
  return <Slot id={SCHEDULE_EDITOR_SLOT} {...props} fallback={unavailable} errorFallback={unavailable} />;
}
