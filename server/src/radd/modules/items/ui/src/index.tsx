import { searchSource } from "./lookups";
import { definePlugin, SlotId, ChangeLine, type HistoryChange } from "@radd/plugin-sdk";
import { itemChange, HISTORY_FIELD_LABELS } from "./change-format";
function ItemChangeLine({ change }: { change: HistoryChange }) {
  if (!change.redacted && change.field === "flagged" && "to" in change) return change.to ? "Flagged this issue" : "Removed the flag";
  return <ChangeLine change={itemChange(change)} />;
}
export default definePlugin({ querySources: [searchSource], contributions: [{ id: "change-line", slot: SlotId.entityChangeLine, match: "item", toggleable: false,
  render: props => <ItemChangeLine change={props.change as HistoryChange} />,
}, {id: "change-fields", slot: SlotId.entityChangeFields, toggleable: false,
  render: props => !props.entityType || props.entityType === "item" ? <>{Object.keys(HISTORY_FIELD_LABELS).map(field => <option key={field} value={field} />)}</> : null,
}] });
