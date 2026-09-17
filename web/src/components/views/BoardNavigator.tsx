import type { ViewGroup } from "../../lib/view-utils";
import { Select } from "../Select";

export function BoardNavigator({columns,lanes,onColumn,onLane,updating}:{columns:ViewGroup[];lanes?:ViewGroup[];onColumn:(key:string)=>void;onLane?:(key:string)=>void;updating?:boolean}) {
  return <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-subtle px-5 py-2">
    <Select value="" placeholder="Jump to column…" aria-label="Jump to column" size="sm" searchable
      className="w-56" options={columns.map(g=>({value:g.key,label:`${g.label} · ${g.total??g.items.length}`}))} onChange={onColumn} />
    {lanes&&onLane&&<Select value="" placeholder="Jump to lane…" aria-label="Jump to lane" size="sm" searchable
      className="w-56" options={lanes.map(g=>({value:g.key,label:`${g.label} · ${g.total??g.items.length}`}))} onChange={onLane} />}
    {updating&&<span role="status" className="text-xs text-fg-muted">Updating totals…</span>}
  </div>;
}
