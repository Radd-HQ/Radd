/** Transitional adapter; backup owns scheduling UI and requests. */
import { Slot } from "@radd/plugin-sdk";
import { SCHEDULE_EDITOR_SLOT, type ScheduleEditorProps } from "../../../../server/src/radd/modules/backup/ui/src/schedule-contract";
export { defaultSchedule, isScheduleValid } from "@radd/plugin-sdk";
export function ScheduleEditor(props: ScheduleEditorProps) {
  const unavailable = <p role="status" className="text-xs text-fg-secondary">Schedule editor unavailable. Your schedule is preserved.</p>;
  return <Slot id={SCHEDULE_EDITOR_SLOT} {...props} fallback={unavailable} errorFallback={unavailable} />;
}
