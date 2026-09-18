import type { Item } from "./types";

/** Exact details also embed parent/epic/link labels. Collections stay broad:
 * an edit can bring a previously absent issue into their result set. */
export function itemInterests(item: Item | undefined): string[] | undefined {
  if (!item?.id) return undefined;
  const ids = new Set([item.id]);
  if (item.parent) ids.add(item.parent.id);
  if (item.epic) ids.add(item.epic.id);
  for (const link of [...(item.links?.incoming ?? []), ...(item.links?.outgoing ?? [])]) {
    ids.add(link.item.id);
  }
  return ids.size <= 128 ? [...ids] : undefined;
}
