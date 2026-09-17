import { useRef } from "react";

/** Preserve existing batch membership on append. Removing IDs drops them from
 * active requests; entity invalidation remains the authority for freshness. */
export function useStableItemBatches(ids: readonly string[], size = 200): string[][] {
  const previous = useRef<string[][]>([]);
  const wanted = new Set(ids);
  const batches = previous.current.map(batch => batch.filter(id => wanted.has(id))).filter(batch => batch.length);
  const known = new Set(batches.flat());
  const added = [...wanted].filter(id => !known.has(id)).sort();
  for (let i = 0; i < added.length; i += size) batches.push(added.slice(i, i + size));
  previous.current = batches;
  return batches;
}
