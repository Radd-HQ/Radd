import { useState } from "react";
import { useInfiniteQuery, useQueries } from "@tanstack/react-query";
import { api } from "./api";
import { entityMeta, Entity } from "./cache";
import { groupItemsForView } from "./view-utils";
import type { Cycle, Item, View } from "./types";

type GroupPage = { cells: {column:string;lane:string;total:number;items:Item[]}[]; total_groups:number;column_totals:Record<string,number>;lane_totals:Record<string,number>;column_points?:Record<string,number>|null };
export function useGroupedItems(view: View | undefined, axis: string | null, lane: string | null, cycles: Cycle[] | undefined, enabled: boolean) {
  const scope = JSON.stringify([view?.id,view?.project_id,view?.query,view?.query_string,axis,lane,view?.hidden_columns,view?.cycle_filter,view?.column_order,view?.swimlane_order]);
  const [position,setPosition] = useState({scope,group:0});
  const group = position.scope === scope ? position.group : 0;
  const cycleIds = groupItemsForView([], "cycle", {cycles,cycleFilter:view?.cycle_filter}).flatMap(g => g.cycleId ? [g.cycleId] : []);
  const request = {project_id:view?.project_id,q:view?.query ?? "",axis,lane,hidden_columns:view?.hidden_columns ?? [],column_order:view?.column_order ?? [],lane_order:view?.swimlane_order ?? [],cycle_ids:axis === "cycle" || lane === "cycle" ? cycleIds : null,cycle_scope:axis === "cycle" || lane === "cycle",group_offset:group * 20};
  const query = useInfiniteQuery({
    queryKey:["grouped-view-items",request], meta:entityMeta(Entity.item,Entity.cycle,Entity.view),
    queryFn:({signal,pageParam}) => {
      const params = new URLSearchParams();
      for (const [key,value] of Object.entries({...request,item_offset:pageParam,item_limit:25,group_limit:20})) {
        if (value === null || value === undefined) continue;
        for (const part of Array.isArray(value) ? value : [value]) params.append(key,String(part));
      }
      return api.get<GroupPage>(`/items/grouped?${params}`,{signal});
    },
    enabled, initialPageParam:0,
    getNextPageParam:(last,pages) => last.cells.some(c => c.total > pages.length * 25) ? pages.length * 25 : undefined,
  });
  const extraScope = JSON.stringify([scope, group, cycleIds]);
  const [extraState, setExtra] = useState<{scope:string; columns:Record<string, number[]>}>({scope:extraScope, columns:{}});
  const extra = extraState.scope === extraScope ? extraState.columns : {};
  const basePages = query.data?.pages.length ?? 1;
  const extraRequests = Object.entries(extra).flatMap(([key, offsets]) => offsets.filter(offset => offset >= basePages * 25).map(offset => ({key, offset})));
  const extraQueries = useQueries({queries: extraRequests.map(({key,offset}) => ({
    queryKey:["grouped-column-items",request,key,offset], meta:entityMeta(Entity.item,Entity.cycle,Entity.view), enabled,
    queryFn:({signal}:{signal:AbortSignal}) => {
      const params = new URLSearchParams();
      for (const [name,value] of Object.entries({...request,column_key:key,group_offset:0,item_offset:offset,item_limit:25,group_limit:20})) {
        if (value === null || value === undefined) continue;
        for (const part of Array.isArray(value) ? value : [value]) params.append(name,String(part));
      }
      return api.get<GroupPage>(`/items/grouped?${params}`,{signal});
    },
  }))});
  const first = enabled ? query.data?.pages[0] : undefined;
  const pages = enabled ? [...(query.data?.pages ?? []), ...extraQueries.flatMap(q=>q.data?[q.data]:[])] : [];
  const items = [...new Map(pages.flatMap(p => p.cells.flatMap(c => c.items)).map(i => [i.id,i])).values()];
  const hasNextPage = Boolean(query.hasNextPage && first?.cells.some(cell => {
    const loaded = new Set(pages.flatMap(page => page.cells.filter(c=>c.column===cell.column && c.lane===cell.lane).flatMap(c=>c.items.map(item=>item.id))));
    return loaded.size < cell.total;
  }));
  return {...query,hasNextPage,items,first,group,
    loadColumn:(key:string)=>{
      const failed = extraQueries.filter((q,i)=>extraRequests[i].key===key&&q.isError);
      if(failed.length) failed.forEach(q=>void q.refetch());
      else setExtra(current=>{
        const columns = current.scope === extraScope ? current.columns : {};
        const offsets = columns[key] ?? [];
        const offset = Math.max(basePages * 25, ...offsets.map(n=>n+25));
        return {scope:extraScope, columns:{...columns,[key]:[...offsets,offset]}};
      });
    },
    columnLoading:(key:string)=>extraQueries.some((q,i)=>extraRequests[i].key===key&&q.isFetching),
    columnError:(key:string)=>extraQueries.some((q,i)=>extraRequests[i].key===key&&q.isError),
    setGroup:(g:number)=>setPosition({scope,group:g})};
}
