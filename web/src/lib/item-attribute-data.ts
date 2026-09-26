import { createContext, useContext } from "react";
import {
  ITEM_ATTRIBUTE_BATCH_MAX,
  useContributedQueries,
  type ItemAttribute,
  type ItemAttributeBatchArgs,
} from "@radd/plugin-sdk";
import { useStableItemBatches } from "./useStableItemBatches";

/**
 * Plugin-contributed item attributes on a surface (RADD-1394): which ones exist, and each shown
 * one's per-item values. A surface provides it once; list cells, board cards, swimlanes and the
 * card designer's preview read it, so no prop threads a plugin's data through the host.
 */
export interface ItemAttributeData {
  /** Every contributed attribute that is loaded and turned on, by id. */
  byId: ReadonlyMap<string, ItemAttribute>;
  /** An item's value — undefined while its batch loads, when it has none, or when the source is gone. */
  valueOf: (attribute: ItemAttribute, itemId: string) => unknown;
}

const NONE: ItemAttributeData = { byId: new Map(), valueOf: () => undefined };
export const ItemAttributeContext = createContext<ItemAttributeData>(NONE);
export const useItemAttributeData = (): ItemAttributeData => useContext(ItemAttributeContext);

/**
 * Asks each SHOWN attribute's source once per page of rows: the page's items are cut into stable
 * batches (appending a page asks only for the new ids), and one contributed query per (source,
 * batch) is shared by every surface and by attributes that share a source. A source that is
 * withdrawn asks nothing and its in-flight read is aborted with the owner's queries.
 */
export function useItemAttributeValues(
  attributes: readonly ItemAttribute[],
  shown: readonly ItemAttribute[],
  itemIds: readonly string[],
): ItemAttributeData {
  const sources = [...new Set(shown.map((attribute) => attribute.source))];
  const batches = useStableItemBatches(sources.length > 0 ? itemIds : [], ITEM_ATTRIBUTE_BATCH_MAX);
  const requests = sources.flatMap((key) =>
    batches.map((ids) => ({ key, args: { ids } satisfies ItemAttributeBatchArgs })),
  );
  const results = useContributedQueries<Record<string, unknown>>(requests);
  const bySource = new Map<string, Record<string, unknown>>();
  results.forEach((result, index) => {
    if (!result.data) return;
    const key = requests[index].key;
    bySource.set(key, { ...bySource.get(key), ...result.data });
  });
  return {
    byId: new Map(attributes.map((attribute) => [attribute.id, attribute])),
    valueOf: (attribute, itemId) => bySource.get(attribute.source)?.[itemId],
  };
}
