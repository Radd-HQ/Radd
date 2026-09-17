import { useEffect, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { infiniteViewItemsQuery } from "./queries/views";
import { api } from "./api";
import { entityMeta, Entity } from "./cache";
import type { View } from "./types";

const AUTO_PAGES = 10;
/** Bounded automatic loading of sprint work; backlog pagination never changes this key. */
export function usePlanningSprints(view: View | undefined, enabled: boolean) {
  const query = useInfiniteQuery({ ...infiniteViewItemsQuery(view), enabled });
  const count = useQuery({
    queryKey: ["planning-sprint-count", view?.query_string],
    meta: entityMeta(Entity.item, Entity.cycle),
    queryFn: ({ signal }) => api.get<{ total: number }>(`/items/count?${view?.query_string}`, { signal }),
    enabled,
  });
  const [cap, setCap] = useState(AUTO_PAGES);
  useEffect(() => setCap(AUTO_PAGES), [view?.query_string]);
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
    more: enabled && query.hasNextPage,
    paused: enabled && query.hasNextPage && loaded >= cap,
    loadMore: () => { setCap(current => current + AUTO_PAGES); void query.fetchNextPage(); },
  };
}
