import type { AutomationCatalog } from "./types";
export function triggerLabel(trigger: string, catalog?: AutomationCatalog): string {
  return catalog?.trigger_kinds.find(kind => kind.key === trigger)?.label
    ?? catalog?.triggers.find(event => event.event_type === trigger)?.label ?? trigger;
}
