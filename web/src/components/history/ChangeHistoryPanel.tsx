import { Slot, SlotId } from "@radd/plugin-sdk";
/** Transitional entity editor adapter. History providers own access, queries and rendering. */
export function ChangeHistoryPanel(props: {entityType: string; entityId: string; projectId?: string; title?: string}) {
  return <Slot id={SlotId.entityHistory} {...props} />;
}
