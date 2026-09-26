import { MANUAL_TRIGGER, SCHEDULE_TRIGGER, VALIDATE_TRIGGER, type AutomationCatalog } from "./types";

/** The trigger keys that are not event types: nothing on the event stream fires them, and they carry no payload. */
export const isSentinelTrigger = (trigger: string) =>
  trigger === MANUAL_TRIGGER || trigger === SCHEDULE_TRIGGER || trigger === VALIDATE_TRIGGER;

export function triggerLabel(trigger: string, catalog?: AutomationCatalog): string {
  return catalog?.trigger_kinds.find(kind => kind.key === trigger)?.label
    ?? catalog?.triggers.find(event => event.event_type === trigger)?.label ?? trigger;
}
