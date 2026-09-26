import { useMemo, type ReactNode } from "react";
import type { PluginContribution } from "./plugin";
import { metaContribution, ownedMetaId, Slot, SlotId, useSlot } from "./slots";
import type { Item } from "./types";

/** Item attributes: one declaration gives a list column and a board-card cell — a slot contribution
 *  (`item.attribute`, `match` = its id) whose data is one of the plugin's own `querySources`. */

/** Where a cell renders; the plugin may size or phrase its chip per surface. */
export const ItemAttributeSurface = { list: "list", card: "card" } as const;
export type ItemAttributeSurfaceValue = (typeof ItemAttributeSurface)[keyof typeof ItemAttributeSurface];

/** The most ids one `fetch` receives — the host asks once per page of rows, in chunks this size. */
export const ITEM_ATTRIBUTE_BATCH_MAX = 200;

/** The arguments an attribute's query source is called with. */
export interface ItemAttributeBatchArgs extends Record<string, unknown> { ids: string[] }

export interface ItemAttributeCellProps<V = unknown> {
  item: Item;
  /** This item's value from the batch. Never null: an item the batch did not answer for renders
   *  the host's empty treatment (a dash in lists, no cell on cards) without calling you. */
  value: V;
  surface: ItemAttributeSurfaceValue;
}

export interface ItemAttributeSpec<V = unknown> {
  /** `<plugin>.<name>` — what saved views and card layouts store. The plugin prefix keeps it clear
   *  of the builtin columns, of `cf.<key>` custom fields and of every other plugin. */
  id: string;
  label: string;
  /** Default and minimum list-column width, in px. */
  width: number;
  minWidth: number;
  /** The key of one of THIS plugin's `querySources`: `fetch({ids}, signal)` resolves to
   *  `{[itemId]: value}` for the ids that have a value (at most ITEM_ATTRIBUTE_BATCH_MAX). */
  source: string;
  /** What the card designer's preview renders; without one it shows the label. */
  sample?: V;
  render: (props: ItemAttributeCellProps<V>) => ReactNode;
}

/** A contributed attribute as the host sees it: the spec's data plus its owner. */
export interface ItemAttribute {
  id: string;
  label: string;
  width: number;
  minWidth: number;
  source: string;
  sample?: unknown;
  plugin: string;
}

/** The contribution row for `definePlugin({ contributions: [itemAttribute({...})] })`. */
export function itemAttribute<V>(spec: ItemAttributeSpec<V>): PluginContribution {
  return metaContribution(SlotId.itemAttribute, "attribute", spec, `${spec.label} column and card cell`);
}

const isWidth = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value > 0;

/** Validate one registered row: an id outside its owner's namespace (or dressed as a custom field)
 *  would let a plugin shadow a builtin, a field or another plugin, so it is refused outright. */
function attributeOf(plugin: string, match: string | undefined, meta: Readonly<Record<string, unknown>> | undefined): ItemAttribute | null {
  const id = ownedMetaId(plugin, match, meta);
  if (!meta || !id || id.startsWith("cf.")) return null;
  if (typeof meta.label !== "string" || !meta.label || !isWidth(meta.width) || !isWidth(meta.minWidth)) return null;
  if (typeof meta.source !== "string" || !meta.source.startsWith(`${plugin}.`)) return null;
  return { id, label: meta.label, width: meta.width, minWidth: Math.min(meta.minWidth, meta.width),
    source: meta.source, sample: meta.sample, plugin };
}

/** Every contributed attribute that is registered AND turned on (either toggle scope hides it). */
export function useItemAttributes(): ItemAttribute[] {
  const entries = useSlot(SlotId.itemAttribute);
  return useMemo(() => {
    const seen = new Set<string>();
    const out: ItemAttribute[] = [];
    for (const entry of entries) {
      const attribute = attributeOf(entry.plugin, entry.contribution.match, entry.contribution.meta);
      if (!attribute || seen.has(attribute.id)) continue;
      seen.add(attribute.id);
      out.push(attribute);
    }
    return out;
  }, [entries]);
}

/** The owner's cell for one item, inside the slot's error boundary: a throw shows `fallback`.
 *  `item` is the host's hydrated, permission-scoped item — the owner reads it as the SDK `Item`. */
export function ItemAttributeCell({ attribute, item, value, surface, fallback = null }: {
  attribute: ItemAttribute;
  item: { id: string };
  value: unknown;
  surface: ItemAttributeSurfaceValue;
  fallback?: ReactNode;
}): ReactNode {
  return <Slot id={SlotId.itemAttribute} match={attribute.id} owner={attribute.plugin} item={item} value={value} surface={surface}
    fallback={fallback} errorFallback={fallback} />;
}
