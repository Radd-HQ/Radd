import type { QueryClient } from "@tanstack/react-query";

/** Invalidate shared queries by their declared entity tags. */
export function invalidateEntities(queryClient: QueryClient, ...entities: string[]) {
  const wanted = new Set<string>(entities);
  return queryClient.invalidateQueries({
    predicate: (query) => {
      const tags = (query.meta as {entities?: string[]} | undefined)?.entities;
      return Array.isArray(tags) && tags.some((tag) => wanted.has(tag));
    },
  });
}
