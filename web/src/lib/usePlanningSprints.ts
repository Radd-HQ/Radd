import { useEffect, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { infiniteViewItemsQuery } from "./queries/views";
import { api } from "./api";
import { entityMeta, Entity } from "./cache";
import type { View } from "./types";

const AUTO_PAGES = 10;
export function planningCountQuery(view: View | undefined) {
  return {
    queryKey: ["planning-count", view?.query_string],
    meta: entityMeta(Entity.item, Entity.cycle),
    queryFn: ({ signal }: { signal: AbortSignal }) => api.get<{ total: number }>(`/items/count?${view?.query_string}`, { signal }),
  };
}
/** Bounded automatic loading of sprint work; backlog pagination never changes this key. */
export function usePlanningSprints(view: View | undefined, enabled: boolean, autoPages = AUTO_PAGES) {
  const query = useInfiniteQuery({ ...infiniteViewItemsQuery(view), enabled });
  const count = useQuery({ ...planningCountQuery(view), enabled });
  const [cap, setCap] = useState(autoPages);
  useEffect(() => setCap(autoPages), [view?.query_string, autoPages]);
  const loaded = query.data?.pages.length ?? 0;
  useEffect(() => {
    if (enabled && query.hasNextPage && !query.isFetchingNextPage && !query.isFetchNextPageError && loaded < cap) {
      void query.fetchNextPage();
    }
  }, [enabled, loaded, cap, query.hasNextPage, query.isFetchingNextPage, query.isFetchNextPageError, query.fetchNextPage]);
  return {
    ...query,
    items: enabled ? query.data?.pages.flat() ?? [] : [],
    total: enabled ? count.data?.total : 0,
    countError: enabled && count.isError,
    more: enabled && query.hasNextPage,
    paused: enabled && query.hasNextPage && loaded >= cap,
    loadMore: () => { setCap(current => current + autoPages); void query.fetchNextPage(); },
  };
}
