import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidation by ENTITY, not query key (docs/modules.md → "Frontend cache invalidation"): a read
 * declares what it caches (`meta: entityMeta(Entity.item)`), a mutation invalidates by entity
 * (`invalidateEntities(queryClient, Entity.item)`), so queries added later are covered automatically.
 * The vocabulary is the SDK's (RADD-1467) so the host and every plugin UI spell a tag once.
 */

/** One tag per cacheable domain entity the host's realtime map produces — extend it as modules
 *  are added. A plugin's OWN entities are not here: it tags them with its server entity type
 *  verbatim (`"sla_policy"`), which the host subscribes to as that exact string (RADD-1396). */
export const Entity = {
  item: "item",
  comment: "comment",
  cycle: "cycle",
  cycleSeries: "cycleSeries",
  release: "release",
  view: "view",
  label: "label",
  team: "team",
  group: "group",
  field: "field",
  accessGrant: "accessGrant",
  worklog: "worklog",
  workCategory: "workCategory",
  automation: "automation",
  form: "form",
  role: "role",
  member: "member",
  project: "project",
  transition: "transition",
  webLink: "webLink",
  vcsLink: "vcsLink",
  notification: "notification",
  watcher: "watcher",
  attachment: "attachment",
  cannedResponse: "cannedResponse",
  serviceAccount: "serviceAccount",
  cardLayoutPreset: "cardLayoutPreset",
  docSpace: "docSpace",
  page: "page",
  dashboard: "dashboard",
} as const;

export type EntityTag = (typeof Entity)[keyof typeof Entity];

/** A cache tag: a shared `Entity` member, or a plugin's own server entity type verbatim. The
 *  `string & {}` keeps the members as completions without closing the set to plugins. */
export type CacheTag = EntityTag | (string & {});

/** What a query's `meta` carries so invalidation and realtime can find it. */
export interface EntityMeta extends Record<string, unknown> {
  entities: CacheTag[];
  /** The query's explicit server-side project filter; absent = all projects. */
  projectId?: string;
  /** The one item the query is about, so a realtime frame for it alone refreshes it. */
  itemId?: string;
  /** An item detail read, whose interests the realtime hub derives from its data. */
  itemDetail?: boolean;
}

/** Spread into a query's `meta` to declare which entities its data caches. */
export function entityMeta(...entities: CacheTag[]): EntityMeta {
  return { entities };
}

export function itemEntityMeta(itemId: string, ...entities: CacheTag[]): EntityMeta {
  return { entities, itemId };
}

/** Declare a query's explicit server-side project filter; absent = all projects. */
export function projectEntityMeta(projectId: string | null | undefined, ...entities: CacheTag[]): EntityMeta {
  return { entities, projectId: projectId || undefined };
}

/** Invalidate every query tagged with any of `entities`. List every entity a mutation changes
 *  (a comment also changes its item's `comment_count`). */
export function invalidateEntities(queryClient: QueryClient, ...entities: CacheTag[]) {
  const wanted = new Set<string>(entities);
  return queryClient.invalidateQueries({
    predicate: (query) => {
      const tags = (query.meta as EntityMeta | undefined)?.entities;
      return Array.isArray(tags) && tags.some((tag) => wanted.has(tag));
    },
  });
}
