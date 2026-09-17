import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "./api";
import { entityMeta, Entity } from "./cache";
import { groupItemsForView } from "./view-utils";
import type { Cycle, Item, View } from "./types";

type GroupPage = { cells: {column:string;lane:string;total:number;items:Item[]}[]; total_groups:number;column_totals:Record<string,number>;lane_totals:Record<string,number> };
export function useGroupedItems(view: View | undefined, axis: string | null, lane: string | null, cycles: Cycle[] | undefined, enabled: boolean) {
  const scope = JSON.stringify([view?.query_string,axis,lane,view?.hidden_columns,view?.cycle_filter,view?.column_order,view?.swimlane_order]);
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
  const first = enabled ? query.data?.pages[0] : undefined;
  const items = [...new Map((enabled ? query.data?.pages ?? [] : []).flatMap(p => p.cells.flatMap(c => c.items)).map(i => [i.id,i])).values()];
  return {...query,items,first,group,setGroup:(g:number)=>setPosition({scope,group:g})};
}
