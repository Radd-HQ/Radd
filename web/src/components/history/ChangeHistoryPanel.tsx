import { Slot, SlotId } from "@radd/plugin-sdk";
/** The entity editors' history panel, rendered through its slot; history providers own access, queries and rendering. */
export function ChangeHistoryPanel(props: {entityType: string; entityId: string; projectId?: string; title?: string}) {
  return <Slot id={SlotId.entityHistory} {...props} />;
}
