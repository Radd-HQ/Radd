import { useState } from "react";
import { useInfiniteQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { entityMeta, Entity } from "./cache";
import { groupItemsForView } from "./view-utils";
import type { Cycle, Item, View } from "./types";

type GroupPage = { cells: {column:string;lane:string;total:number;items:Item[];next_cursor?:string|null}[]; total_groups:number;column_totals:Record<string,number>;lane_totals:Record<string,number>;column_points?:Record<string,number>|null };
export function useGroupedItems(view: View | undefined, axis: string | null, lane: string | null, cycles: Cycle[] | undefined, enabled: boolean) {
  const client = useQueryClient();
  const scope = JSON.stringify([view?.id,view?.project_id,view?.query,view?.query_string,axis,lane,view?.hidden_columns,view?.cycle_filter,view?.column_order,view?.swimlane_order]);
  const [position,setPosition] = useState({scope,group:0});
  const group = position.scope === scope ? position.group : 0;
  const cycleIds = groupItemsForView([], "cycle", {cycles,cycleFilter:view?.cycle_filter}).flatMap(g => g.cycleId ? [g.cycleId] : []);
  const request = {cursor_mode:!lane,project_id:view?.project_id,q:view?.query ?? "",axis,lane,hidden_columns:view?.hidden_columns ?? [],column_order:view?.column_order ?? [],lane_order:view?.swimlane_order ?? [],cycle_ids:axis === "cycle" || lane === "cycle" ? cycleIds : null,cycle_scope:axis === "cycle" || lane === "cycle",group_offset:group * 20};
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
  const [extraState, setExtra] = useState<{scope:string; columns:Record<string, number>}>({scope:extraScope, columns:{}});
  const extra = extraState.scope === extraScope ? extraState.columns : {};
  const extraRequests = Object.entries(extra).map(([key,count])=>({key,count,
    start:query.data?.pages.at(-1)?.cells.find(c=>c.column===key)?.next_cursor ?? null}));
  const extraQueries = useQueries({queries: extraRequests.map(({key,count,start}) => ({
    placeholderData:(previous:GroupPage[]|undefined)=>previous,
    queryKey:["grouped-column-cursors",request,key,count,start], meta:entityMeta(Entity.item,Entity.cycle,Entity.view), enabled:enabled && !lane, retry:false,
    queryFn:async ({signal}:{signal:AbortSignal}) => {
      let after = start;
      const pages:GroupPage[] = [];
      for(let i=0;i<count && after;i++) {
        const params = new URLSearchParams();
        for (const [name,value] of Object.entries({...request,column_key:key,group_offset:0,after,item_limit:25,group_limit:20})) {
          if (value === null || value === undefined) continue;
          for (const part of Array.isArray(value) ? value : [value]) params.append(name,String(part));
        }
        // Keep earlier continuation windows cached on append. Invalidation
        // marks them stale, so a refresh rebuilds the cursor chain in order.
        const page = await client.fetchQuery({queryKey:["grouped-column-window",params.toString()],
          meta:entityMeta(Entity.item,Entity.cycle,Entity.view), staleTime:30_000, retry:false,
          queryFn:()=>api.get<GroupPage>(`/items/grouped?${params}`,{signal})});
        pages.push(page);
        after=page.cells.find(c=>c.column===key)?.next_cursor ?? null;
      }
      return pages;
    },
  }))});
  const columnPages = extraQueries.map((query,i)=> {
    const {key,count,start} = extraRequests[i];
    return query.data ?? client.getQueryData<GroupPage[]>(["grouped-column-cursors",request,key,count-1,start]) ?? [];
  });
  const first = enabled ? query.data?.pages[0] : undefined;
  const pages = enabled ? [...(query.data?.pages ?? []), ...columnPages.flat()] : [];
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
        return {scope:extraScope, columns:{...columns,[key]:(columns[key]??0)+1}};
      });
    },
    columnHasMore:(key:string)=>{
      const index = extraRequests.findIndex(r=>r.key===key);
      const last = index >= 0 ? columnPages[index]?.at(-1) : undefined;
      return Boolean((last ?? query.data?.pages.at(-1))?.cells.find(c=>c.column===key)?.next_cursor);
    },
    columnLoading:(key:string)=>extraQueries.some((q,i)=>extraRequests[i].key===key&&q.isFetching),
    columnError:(key:string)=>extraQueries.some((q,i)=>extraRequests[i].key===key&&q.isError),
    setGroup:(g:number)=>setPosition({scope,group:g})};
}
