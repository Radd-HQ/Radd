import { useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { entityMeta, Entity } from "./cache";
import { groupItemsForView, type ViewGroup } from "./view-utils";
import { CATEGORY_META } from "./meta";
import type { State } from "./types";
import type { Cycle, Item, ItemParentRef, View } from "./types";

const PAGE_SIZE = 25;
const BOARD_STALE_MS = 30_000;
export const BOARD_ALL_LANE = "__all__";
type Page = { cells: {column:string;lane:string;items:Item[];next_cursor:string|null}[];
  column_totals:Record<string,number>;lane_totals:Record<string,number>;
  column_points:Record<string,number>|null;column_labels:Record<string,string>;
  lane_labels:Record<string,string>;epic_refs:Record<string,ItemParentRef> };
const cellId = (column:string,lane:string) => JSON.stringify([column,lane]);
function paramsOf(request:Record<string,unknown>) {
  const params = new URLSearchParams();
  for(const [key,value] of Object.entries(request)) {
    if(value === undefined || value === null) continue;
    for(const part of Array.isArray(value) ? value : [value]) params.append(key,String(part));
  }
  return params.toString();
}

/** Summary identity is independent of cards. Each cursor window has its own
 * cache entry: appending never re-fetches earlier windows or the aggregate. */
export function useBoardItems(view:View|undefined,axis:string|null,lane:string|null,cycles:Cycle[]|undefined,enabled:boolean) {
  const client = useQueryClient();
  const cycleScope = axis === "cycle" || lane === "cycle";
  const request = {project_id:view?.project_id,q:view?.query??"",axis,lane,
    hidden_columns:view?.hidden_columns??[],cycle_scope:cycleScope,
    cycle_ids:cycleScope ? groupItemsForView([],"cycle",{cycles,cycleFilter:view?.cycle_filter}).flatMap(g=>g.cycleId?[g.cycleId]:[]) : null};
  const scope = JSON.stringify([view?.id,request]);
  const meta = entityMeta(Entity.item,Entity.cycle,Entity.view,Entity.team,Entity.member,Entity.field,Entity.project,Entity.accessGrant);
  const summary = useQuery({queryKey:["board-summary",scope],meta,enabled,staleTime:BOARD_STALE_MS,
    queryFn:({signal})=>api.get<Page>(`/items/grouped?${paramsOf({...request,summary_only:true})}`,{signal})});
  const [requested,setRequested] = useState<{scope:string;cells:Record<string,number>}>({scope,cells:{}});
  const wanted = requested.scope === scope ? requested.cells : {};
  const descriptors = Object.entries(wanted).flatMap(([id,count])=>{
    const [column,ln] = JSON.parse(id) as [string,string];
    const result:{id:string;key:readonly unknown[];params:string}[]=[];
    let after:string|null = null;
    for(let i=0;i<count;i++) {
      const params=paramsOf({...request,rows_only:true,cursor_mode:true,column_key:column,lane_key:lane?ln:null,after,item_limit:PAGE_SIZE});
      const key=["board-cell-window",scope,params] as const;
      result.push({id,key,params});
      const cached = client.getQueryData<Page>(key);
      after=cached?.cells[0]?.next_cursor??null;
      if(!after) break;
    }
    return result;
  });
  const queries=useQueries({queries:descriptors.map(({key,params})=>({queryKey:key,meta,enabled,
    staleTime:BOARD_STALE_MS,retry:false,
    queryFn:({signal}:{signal:AbortSignal})=>api.get<Page>(`/items/grouped?${params}`,{signal})}))});
  const items=enabled ? [...new Map(queries.flatMap(q=>q.data?.cells.flatMap(c=>c.items)??[]).map(i=>[i.id,i])).values()] : [];
  const indices=(col:string,ln=BOARD_ALL_LANE)=>descriptors.flatMap((d,i)=>d.id===cellId(col,ln)?[i]:[]);
  const hasMore=(col:string,ln=BOARD_ALL_LANE)=>{
    const last=indices(col,ln).at(-1);
    return last===undefined || Boolean(queries[last].data?.cells[0]?.next_cursor);
  };
  const loading=(col:string,ln=BOARD_ALL_LANE)=>indices(col,ln).some(i=>queries[i].isFetching);
  const cellError=(col:string,ln=BOARD_ALL_LANE)=>indices(col,ln).some(i=>queries[i].isError);
  const load=(col:string,ln=BOARD_ALL_LANE)=>{
    const matches=indices(col,ln);
    if(matches.some(i=>queries[i].isFetching)) return;
    const failed=matches.filter(i=>queries[i].isError);
    if(failed.length) {failed.forEach(i=>void queries[i].refetch());return;}
    if(!hasMore(col,ln)) return;
    setRequested(current=>{
      const cells=current.scope===scope?current.cells:{};
      const id=cellId(col,ln);
      return {scope,cells:{...cells,[id]:(cells[id]??0)+1}};
    });
  };
  return {...summary,scope,items,first:summary.data,load,hasMore,loading,cellError,
    requested:(col:string,ln=BOARD_ALL_LANE)=>Boolean(wanted[cellId(col,ln)])};
}

/** Merge the complete directory into the registry's natural buckets. Dynamic
 * groups no longer disappear just because their cards haven't loaded yet. */
export function boardGroups(base:ViewGroup[],axis:string,summary:Page|undefined,lane=false,states?:State[],registryKeys?:string[]):ViewGroup[] {
  if(!summary) return base;
  const totals=lane?summary.lane_totals:summary.column_totals;
  const labels=(lane?summary.lane_labels:summary.column_labels)??{};
  const groups=new Map(base.map(g=>[g.key,{...g,total:totals[g.key]??0,totalPoints:lane?undefined:summary.column_points?.[g.key]}]));
  for(const key of [...new Set([...Object.keys(labels),...Object.keys(totals)])].sort((a,b)=>(labels[a]??a).localeCompare(labels[b]??b))) if(!groups.has(key)) groups.set(key,{
    key,label:labels[key]??key,items:[],total:totals[key]??0,totalPoints:lane?undefined:summary.column_points?.[key],
    ...(summary.epic_refs?.[key]?{epicRef:summary.epic_refs?.[key]}:{}),
  });
  const result=[...groups.values()];
  if(["assignee","team","epic"].includes(axis)) result.sort((a,b)=>Number(a.key.startsWith("__"))-Number(b.key.startsWith("__"))||a.label.localeCompare(b.label));
  if(axis.startsWith("cf.")&&registryKeys) {
    const order=new Map(registryKeys.filter(k=>k!=="__none__").map((k,i)=>[k,i]));
    result.sort((a,b)=>Number(a.key==="__none__")-Number(b.key==="__none__")
      ||(order.get(a.key)??order.size)-(order.get(b.key)??order.size)||a.label.localeCompare(b.label));
  }
  if(axis==="state"&&states?.length) {
    // Global state buckets are name-keyed. Use workflow semantics even before
    // their first card arrives; loading cannot move a column under the pointer.
    const byName=new Map(states.map(s=>[s.name,s]));
    if(result.every(g=>!totals[g.key] || byName.has(g.key))) {
      result.sort((a,b)=>(CATEGORY_META[byName.get(a.key)?.category??"todo"].order-CATEGORY_META[byName.get(b.key)?.category??"todo"].order)||a.label.localeCompare(b.label));
      for(const g of result) {const state=byName.get(g.key);if(state) g.dotClassName=CATEGORY_META[state.category].dotClassName;}
    }
  }
  return result;
}
export type BoardLoading = Pick<ReturnType<typeof useBoardItems>,"load"|"hasMore"|"loading"|"cellError"|"requested">;
